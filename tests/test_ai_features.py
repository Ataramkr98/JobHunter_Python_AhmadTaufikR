import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from app import create_app
from app.extensions import db
from app.models.employer import Resume
from app.models.job import Company, Job
from app.models.user import User
from app.services import ai_gateway as gateway
from app.services.matching import fit_score, match_jobs, resume_to_profile_text


def provider_response(content, finish="stop"):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": finish}]
    }).encode()
    return response


class AiFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.backend = patch.dict(os.environ, {"MATCHING_BACKEND": "stdlib"})
        self.backend.start()
        self.app = create_app("testing")
        self.app.config.update(
            AI_BASE_URL="https://api.groq.com/openai/v1",
            AI_API_KEY="unit-test-secret",
            AI_MODEL_DEFAULT="openai/gpt-oss-20b",
            AI_MODEL_ANALYZE="", AI_MODEL_CHAT="", AI_MAX_RETRIES=1,
        )
        gateway._CACHE.clear()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        gateway._CACHE.clear()
        self.backend.stop()

    def seed_profile(self):
        company = Company(name="Example", slug="example")
        user = User(email="ai@example.test", display_name="Example User", password_hash="unused")
        db.session.add_all([company, user])
        db.session.flush()
        jobs = [
            Job(company_id=company.id, title="Python Engineer", description="Python SQL APIs", skills=["Python", "SQL", "Docker"], status="active"),
            Job(company_id=company.id, title="Designer", description="Figma design systems", skills=["Figma"], status="active"),
        ]
        resume = Resume(user_id=user.id, headline="Python Engineer", summary="Python SQL APIs", skills=["Python", "SQL"], experiences=[], educations=[])
        db.session.add_all([*jobs, resume])
        db.session.commit()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
        return jobs[0], resume

    def test_groq_payload_and_cache_invalidation(self):
        with self.app.app_context(), patch.object(gateway.urllib.request, "urlopen", return_value=provider_response({"explanation": "Python matches."})) as send:
            messages = [{"role": "user", "content": "JSON Python"}]
            self.assertEqual(gateway.chat_json(messages)["explanation"], "Python matches.")
            gateway.chat_json(messages)
            self.assertEqual(send.call_count, 1)
            payload = json.loads(send.call_args.args[0].data)
            self.assertEqual(payload["max_completion_tokens"], 1200)
            self.assertEqual(payload["reasoning_effort"], "low")
            self.assertFalse(payload["include_reasoning"])
            gateway.chat_json([{"role": "user", "content": "JSON Docker"}])
            self.app.config["AI_MODEL_DEFAULT"] = "openai/gpt-oss-120b"
            gateway.chat_json(messages)
            self.assertEqual(send.call_count, 3)

    def test_transient_error_retries_once(self):
        error = urllib.error.HTTPError("https://provider.invalid", 503, "unavailable", {}, io.BytesIO())
        with self.app.app_context(), patch.object(gateway.urllib.request, "urlopen", side_effect=[error, provider_response({"explanation": "Recovered."})]) as send, patch.object(gateway.time, "sleep"):
            self.assertEqual(gateway.chat_json([])["explanation"], "Recovered.")
            self.assertEqual(send.call_count, 2)

    def test_auth_failure_backs_off_without_leaking_credentials(self):
        error = urllib.error.HTTPError("https://provider.invalid", 401, "unit-test-secret", {}, io.BytesIO(b"unit-test-secret"))
        with self.app.app_context(), patch.object(gateway.urllib.request, "urlopen", side_effect=error) as send:
            for _ in range(2):
                with self.assertRaises(gateway.AiGatewayError) as caught:
                    gateway.chat_json([])
                self.assertNotIn("unit-test-secret", str(caught.exception))
            self.assertEqual(send.call_count, 1)

    def test_invalid_or_truncated_provider_json_is_rejected(self):
        with self.app.app_context():
            for content, finish in [([], "stop"), (None, "stop"), ({}, "stop"), ({"explanation": "cut off"}, "length")]:
                gateway._CACHE.clear()
                with self.subTest(content=content, finish=finish), patch.object(gateway.urllib.request, "urlopen", return_value=provider_response(content, finish)):
                    with self.assertRaises(gateway.AiGatewayError):
                        gateway.chat_json([])

    def test_detail_and_shortlist_scores_agree(self):
        with self.app.app_context():
            job, resume = self.seed_profile()
            profile = resume_to_profile_text(resume)
            ranked = match_jobs(profile, profile_skills=resume.skills)
            detail = fit_score(profile, resume.skills, job)
            self.assertEqual(ranked[0]["job"].id, job.id)
            self.assertEqual(detail["score"], ranked[0]["score"])
            self.assertEqual(detail["matched_skills"], ranked[0]["matched_skills"])
            self.assertEqual(detail["missing_skills"], ["docker"])

    def test_missing_narrative_text_is_rejected_before_success_caching(self):
        with self.app.app_context():
            for content in [{"explanation": []}, {"explanation": " "}, {"other": "unexpected"}]:
                gateway._CACHE.clear()
                with self.subTest(content=content), patch.object(gateway.urllib.request, "urlopen", return_value=provider_response(content)):
                    with self.assertRaises(gateway.AiGatewayError):
                        gateway.chat_json([], required_key="explanation")

    def test_summary_is_visible_on_both_pages_and_escaped(self):
        with self.app.app_context():
            job, _ = self.seed_profile()
            self.app.config["AI_EXPLAIN_MATCHES"] = True
            with patch.object(gateway, "chat_json", return_value={"explanation": "Python matches <script>unsafe</script>"}) as chat:
                for path in ["/resume/matches", f"/jobs/{job.id}"]:
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b"data-ai-explanation", response.data)
                    self.assertIn(b"Python matches &lt;script&gt;unsafe&lt;/script&gt;", response.data)
                    self.assertNotIn(b"Python matches <script>", response.data)
                self.assertEqual(chat.call_count, 2)

    def test_provider_failure_keeps_pages_and_scores_available(self):
        with self.app.app_context():
            job, _ = self.seed_profile()
            self.app.config["AI_EXPLAIN_MATCHES"] = True
            with patch.object(gateway, "chat_json", side_effect=gateway.AiGatewayError("Unavailable")):
                for path in ["/resume/matches", f"/jobs/{job.id}"]:
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b"AI explanation is temporarily unavailable", response.data)

    def test_disabled_feature_and_public_matching_api_make_no_ai_calls(self):
        with self.app.app_context():
            job, _ = self.seed_profile()
            with patch.object(gateway, "chat_json") as chat:
                self.assertEqual(self.client.get(f"/jobs/{job.id}").status_code, 200)
                self.app.config["AI_EXPLAIN_MATCHES"] = True
                response = self.client.post("/api/match", json={"profile_text": "Python SQL", "skills": ["Python"]})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()["data"]["matches"])
                chat.assert_not_called()

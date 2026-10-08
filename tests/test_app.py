import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models.employer import Employer, PostedJob, Resume
from app.models.job import Company, Job, JobSource, Source
from app.models.user import Application, JobAlert, PasswordResetToken, SavedJob, User
from app.services.cron import describe_cron
from app.services.matching import fit_score
from app.services.alerts import due_alert_deliveries
from app.services.normalization import normalize_salary, normalize_title
from app.services import ratelimit
from app.services.resume import safe_web_url
from app.services.urls import safe_local_path


class JobHunterTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        with self.app.app_context():
            company = Company(name="Example Co", slug="example-co")
            source = Source(name="Employer Portal", engine="api", enabled=True)
            seeker = User(email="seeker@example.com", display_name="Seeker")
            seeker.set_password("password123")
            employer_user = User(
                email="employer@example.com", display_name="Employer", is_employer=True
            )
            employer_user.set_password("password123")
            admin = User(email="admin@example.com", display_name="Admin", is_admin=True)
            admin.set_password("password123")
            db.session.add_all([company, source, seeker, employer_user, admin])
            db.session.flush()

            employer = Employer(
                user_id=employer_user.id,
                company_id=company.id,
                company_name=company.name,
            )
            external = Job(
                title="Backend Engineer",
                canonical_title="Backend Engineer",
                company_id=company.id,
                description="Build Python APIs",
                city="Jakarta",
                category="Engineering",
                skills=["Python", "PostgreSQL"],
                status="active",
            )
            posted = Job(
                title="Platform Engineer",
                canonical_title="DevOps Engineer",
                company_id=company.id,
                description="Kubernetes Terraform platform",
                city="Jakarta",
                category="Engineering",
                skills=["Kubernetes", "Terraform"],
                status="active",
            )
            db.session.add_all([employer, external, posted])
            db.session.flush()
            posted_job = PostedJob(
                employer_id=employer.id,
                job_id=posted.id,
                title=posted.title,
                description=posted.description,
                location="Jakarta",
                status="active",
            )
            db.session.add(posted_job)
            db.session.flush()
            db.session.add(JobSource(
                job_id=posted.id,
                source_id=source.id,
                external_id=f"posted-{posted.id}",
                url=f"/jobs/{posted.id}",
            ))
            db.session.commit()

            self.seeker_id = seeker.id
            self.employer_user_id = employer_user.id
            self.admin_user_id = admin.id
            self.external_job_id = external.id
            self.posted_job_id = posted_job.id
            self.posted_canonical_id = posted.id
            self.source_id = source.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        # Return the in-memory database's connections to the pool's dead list so
        # the run does not finish with unclosed-connection ResourceWarnings.
        with self.app.app_context():
            db.engine.dispose()

    def login(self, email="seeker@example.com", password="password123", next_url=None):
        path = "/auth/login"
        if next_url:
            path += f"?next={next_url}"
        return self.client.post(path, data={"email": email, "password": password})

    def test_pages_and_api_handle_malformed_numeric_parameters(self):
        response = self.client.get("/jobs?salary_min=nope&freshness=bad&page=NaN")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/api/jobs?salary_min=nope&page=x&per_page=0&freshness=no")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        pagination = payload["data"]["pagination"]
        self.assertEqual(pagination["page"], 1)
        self.assertGreaterEqual(pagination["pages"], 1)

    def test_api_match_validates_payload_and_bounds_top_n(self):
        self.assertEqual(
            self.client.post("/api/match", json={"profile_text": 123}).status_code,
            400,
        )
        self.assertEqual(self.client.post("/api/match", json=[1, 2, 3]).status_code, 400)
        response = self.client.post(
            "/api/match", json={"profile_text": "Python API engineer", "top_n": "bad"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("matches", response.get_json()["data"])

    def test_api_uses_the_standard_response_envelope(self):
        payload = self.client.get("/api/jobs?per_page=2").get_json()
        self.assertEqual(set(payload), {"success", "message", "data"})
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["data"]["jobs"]), 2)

        missing = self.client.get("/api/jobs/999999")
        self.assertEqual(missing.status_code, 404)
        body = missing.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["data"], {})

        categories = self.client.get("/api/categories").get_json()
        self.assertIn("categories", categories["data"])

    def test_posted_job_has_working_application_flow(self):
        public_page = self.client.get(f"/jobs/{self.posted_canonical_id}")
        self.assertEqual(public_page.status_code, 200)
        self.assertIn(b"Log in to apply", public_page.data)
        self.assertNotIn(b"Apply on Employer Portal", public_page.data)

        self.login()
        response = self.client.post(
            f"/employer/jobs/{self.posted_job_id}/apply",
            data={"cover_note": "I am interested."},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            application = Application.query.filter_by(
                user_id=self.seeker_id, job_id=self.posted_canonical_id
            ).one()
            self.assertEqual(application.posted_job_id, self.posted_job_id)
            self.assertEqual(application.cover_note, "I am interested.")

        page = self.client.get(f"/jobs/{self.posted_canonical_id}")
        self.assertIn(b"Application submitted", page.data)

    def test_closed_job_cannot_be_saved_tracked_or_applied_to(self):
        self.login()
        with self.app.app_context():
            posted = db.session.get(PostedJob, self.posted_job_id)
            posted.status = "closed"
            posted.job.status = "expired"
            db.session.commit()
        self.assertEqual(
            self.client.post(f"/employer/jobs/{self.posted_job_id}/apply").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(f"/jobs/{self.posted_canonical_id}/save").status_code,
            404,
        )

    def test_login_rejects_external_redirect_and_logout_requires_post(self):
        response = self.login(next_url="https://evil.example/steal")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        self.assertEqual(self.client.post("/auth/logout").status_code, 302)

    def test_account_deletion_erases_personal_records_and_invalidates_login(self):
        with self.app.app_context():
            db.session.add_all([
                SavedJob(user_id=self.seeker_id, job_id=self.external_job_id),
                Application(user_id=self.seeker_id, job_id=self.external_job_id, notes="private"),
                Resume(
                    user_id=self.seeker_id,
                    full_name="Private Name",
                    email="private@example.com",
                    phone="123",
                ),
                JobAlert(
                    user_id=self.seeker_id,
                    name="Private alert",
                    query={"q": "secret"},
                    unsubscribe_token="test-token",
                ),
            ])
            db.session.commit()

        self.login()
        self.assertEqual(self.client.post("/account/delete").status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, self.seeker_id)
            self.assertIsNotNone(user.deleted_at)
            self.assertEqual(user.default_location, "")
            self.assertEqual(SavedJob.query.filter_by(user_id=user.id).count(), 0)
            self.assertEqual(Application.query.filter_by(user_id=user.id).count(), 0)
            self.assertEqual(Resume.query.filter_by(user_id=user.id).count(), 0)
            self.assertEqual(db.session.query(JobAlert).filter_by(user_id=user.id).count(), 0)

        response = self.client.post(
            "/auth/login", data={"email": "seeker@example.com", "password": "password123"}
        )
        self.assertIn(b"Invalid email or password", response.data)

    def test_sqlite_foreign_keys_and_health_check(self):
        with self.app.app_context():
            enabled = db.session.execute(text("PRAGMA foreign_keys")).scalar_one()
            self.assertEqual(enabled, 1)
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["database"], "ok")

    def test_error_pages_render_the_branded_shell(self):
        """A missing page must not fall back to Werkzeug's default white screen."""
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"JobHunter", response.data)
        self.assertIn(b"could not find that page", response.data)

        # The same page renders inside the workspace shell when signed in, which
        # previously crashed because request.endpoint is None on a 404.
        self.login()
        signed_in = self.client.get("/no-such-page")
        self.assertEqual(signed_in.status_code, 404)
        self.assertIn(b"could not find that page", signed_in.data)

        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        forbidden = self.client.get("/admin")
        self.assertEqual(forbidden.status_code, 403)
        self.assertIn(b"do not have access", forbidden.data)

    def test_api_errors_stay_json_on_failure(self):
        response = self.client.get("/api/jobs/999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.mimetype, "application/json")

    def test_unhandled_exception_renders_branded_500_page(self):
        app = create_app("testing")
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.route("/_probe_boom")
        def _boom():
            raise RuntimeError("intentional failure")

        try:
            response = app.test_client().get("/_probe_boom")
            self.assertEqual(response.status_code, 500)
            self.assertIn(b"Something went wrong", response.data)
            self.assertNotIn(b"intentional failure", response.data)
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_security_headers_are_applied_to_every_response(self):
        for path in ["/", "/jobs", "/no-such-page"]:
            with self.subTest(path=path):
                headers = self.client.get(path).headers
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["X-Frame-Options"], "DENY")
                self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
                self.assertEqual(headers["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_login_is_rate_limited_after_repeated_failures(self):
        self.app.config["LOGIN_RATE_LIMIT"] = 3
        self.app.config["LOGIN_RATE_WINDOW"] = 300
        email = "brute-force-target@example.com"

        for _ in range(3):
            attempt = self.client.post(
                "/auth/login", data={"email": email, "password": "wrong-password"}
            )
            self.assertEqual(attempt.status_code, 200)

        blocked = self.client.post(
            "/auth/login", data={"email": email, "password": "wrong-password"}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn(b"Too many failed attempts", blocked.data)

    def test_robots_and_sitemap_are_served(self):
        robots = self.client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn(b"Disallow: /admin", robots.data)
        self.assertIn(b"Sitemap:", robots.data)

        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        self.assertEqual(sitemap.mimetype, "application/xml")
        self.assertIn(b"<urlset", sitemap.data)
        self.assertIn(f"/jobs/{self.external_job_id}".encode(), sitemap.data)

    def test_search_pagination_is_windowed(self):
        """A large result set must not render one link per page."""
        from app.models.job import Company

        with self.app.app_context():
            company = Company.query.first()
            db.session.add_all([
                Job(title=f"Backend Engineer {i}", canonical_title="Backend Engineer",
                    company_id=company.id, city="Jakarta", category="Engineering",
                    status="active", description="Python APIs")
                for i in range(60)
            ])
            db.session.commit()

        response = self.client.get("/jobs")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"pagination-meta", response.data)
        # 61 jobs at 10/page = 7 pages, but only a window of links is emitted.
        self.assertLess(response.data.count(b'<a href="/jobs?page='), 8)

    def test_role_pages_render_without_server_errors(self):
        self.login()
        for path in ["/", "/saved", "/applications", "/account", "/alerts", "/resume"]:
            with self.subTest(role="seeker", path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/admin").status_code, 403)
        self.client.post("/auth/logout")

        self.login("employer@example.com")
        for path in ["/employer", "/employer/post", f"/employer/jobs/{self.posted_job_id}"]:
            with self.subTest(role="employer", path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.client.post("/auth/logout")

        self.login("admin@example.com")
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_due_alerts_advance_cursor_and_do_not_repeat(self):
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            job = db.session.get(Job, self.external_job_id)
            job.posted_at = now - timedelta(hours=1)
            alert = JobAlert(
                user_id=self.seeker_id,
                name="Backend",
                query={"q": "backend"},
                frequency="daily",
                created_at=now - timedelta(days=2),
                unsubscribe_token="due-alert-token",
            )
            db.session.add(alert)
            db.session.commit()

            deliveries = due_alert_deliveries(now)
            self.assertEqual(len(deliveries), 1)
            self.assertEqual([item.id for item in deliveries[0]["jobs"]], [job.id])
            self.assertEqual(due_alert_deliveries(now), [])

    def test_normalization_matching_and_url_edge_cases(self):
        self.assertEqual(normalize_salary("IDR 8,5-12 jt/bulan")["min"], 8_500_000)
        self.assertEqual(normalize_salary("IDR 8.000.000")["min"], 8_000_000)
        self.assertEqual(normalize_title("Equipment Operator")[0], "Other")
        self.assertEqual(normalize_title("Product Manager")[0], "Product Manager")
        self.assertEqual(safe_web_url("javascript:alert(1)"), "")
        self.assertEqual(safe_web_url("example.com"), "https://example.com")

        # Redirect targets must stay same-origin.
        self.assertEqual(safe_local_path("/saved"), "/saved")
        self.assertEqual(safe_local_path("/jobs?q=python"), "/jobs?q=python")
        for hostile in ["https://evil.example/steal", "//evil.example", "/\\evil.example",
                        "javascript:alert(1)", "saved", "", None,
                        "/a\r\nSet-Cookie: x=1"]:
            with self.subTest(target=hostile):
                self.assertEqual(safe_local_path(hostile, "/fallback"), "/fallback")

        class StopWordsOnlyJob:
            skills = ["Python"]

            @staticmethod
            def search_text():
                return "the and or"

        result = fit_score("the and", [], StopWordsOnlyJob())
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["missing_skills"], ["python"])

    # ------------------------------------------------------------------ #
    # Password reset
    # ------------------------------------------------------------------ #
    def test_password_reset_round_trip_uses_a_single_use_hashed_token(self):
        """A reset must change the password, never leak the token, and never
        be replayable."""
        # The mail adapter logs at INFO; capture the root logger so the test does
        # not depend on which logger name the app happens to use.
        with self.assertLogs(level="INFO") as captured:
            response = self.client.post(
                "/auth/forgot-password",
                data={"email": "seeker@example.com"},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        # Neutral wording: the page must not confirm the address exists.
        self.assertIn(b"If an account exists", response.data)

        with self.app.app_context():
            rows = PasswordResetToken.query.all()
            self.assertEqual(len(rows), 1)
            stored = rows[0]
            self.assertIsNone(stored.used_at)
            # The plaintext must never be persisted.
            log_text = "\n".join(captured.output)
            link = log_text.split("reset-password/")[-1].split()[0]
            self.assertNotIn(link, stored.token_hash)
            self.assertEqual(
                PasswordResetToken.hash_token(link), stored.token_hash,
            )

        # Mismatched confirmation is rejected.
        mismatch = self.client.post(
            f"/auth/reset-password/{link}",
            data={"password": "brand-new-secret", "password_confirm": "different"},
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertIn(b"do not match", mismatch.data)

        accepted = self.client.post(
            f"/auth/reset-password/{link}",
            data={"password": "brand-new-secret", "password_confirm": "brand-new-secret"},
            follow_redirects=True,
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertIn(b"Password updated", accepted.data)

        with self.app.app_context():
            self.assertTrue(
                db.session.get(User, self.seeker_id).check_password("brand-new-secret")
            )
            self.assertIsNotNone(
                db.session.get(PasswordResetToken, stored.id).used_at
            )

        # Replaying the same link must fail.
        replay = self.client.post(
            f"/auth/reset-password/{link}",
            data={"password": "another-secret-1", "password_confirm": "another-secret-1"},
            follow_redirects=True,
        )
        self.assertIn(b"expired", replay.data)

    def test_password_reset_never_confirms_whether_an_account_exists(self):
        with self.app.app_context():
            other = User(email="known@example.com", display_name="Known")
            other.set_password("password123")
            db.session.add(other)
            db.session.commit()

        known = self.client.post(
            "/auth/forgot-password", data={"email": "known@example.com"},
            follow_redirects=True,
        )
        unknown = self.client.post(
            "/auth/forgot-password", data={"email": "nobody@example.com"},
            follow_redirects=True,
        )
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertIn(b"If an account exists", known.data)
        self.assertIn(b"If an account exists", unknown.data)
        with self.app.app_context():
            self.assertEqual(PasswordResetToken.query.count(), 1)

    def test_issuing_a_new_reset_invalidates_the_previous_link(self):
        with self.app.app_context():
            user = db.session.get(User, self.seeker_id)
            first_row, first_plain = user.issue_reset_token()
            db.session.commit()
            second_row, second_plain = user.issue_reset_token()
            db.session.commit()
            self.assertNotEqual(first_plain, second_plain)
            self.assertIsNotNone(db.session.get(PasswordResetToken, first_row.id).used_at)

        stale = self.client.get(f"/auth/reset-password/{first_plain}",
                                follow_redirects=True)
        self.assertIn(b"expired", stale.data)
        self.assertEqual(
            self.client.get(f"/auth/reset-password/{second_plain}").status_code, 200
        )

    # ------------------------------------------------------------------ #
    # Unsubscribe / API hardening / sitemap
    # ------------------------------------------------------------------ #
    def test_unsubscribe_requires_confirmation_rather_than_changing_state_on_get(self):
        """Email clients prefetch links, so a GET must not pause an alert."""
        with self.app.app_context():
            alert = JobAlert(
                user_id=self.seeker_id, name="Backend", query={"q": "backend"},
                unsubscribe_token="unsub-token-abc",
            )
            db.session.add(alert)
            db.session.commit()

        preview = self.client.get("/alerts/unsubscribe/unsub-token-abc")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"Stop this alert", preview.data)
        with self.app.app_context():
            self.assertTrue(
                db.session.query(JobAlert)
                .filter_by(unsubscribe_token="unsub-token-abc").one().active
            )

        confirmed = self.client.post("/alerts/unsubscribe/unsub-token-abc")
        self.assertEqual(confirmed.status_code, 302)
        with self.app.app_context():
            self.assertFalse(
                db.session.query(JobAlert)
                .filter_by(unsubscribe_token="unsub-token-abc").one().active
            )

    def test_api_rate_limit_returns_429_with_retry_after(self):
        # The limiter is process-global, so clear it first rather than relying
        # on this test running before any other that touches /api.
        ratelimit.reset_all()
        self.app.config["API_RATE_LIMIT"] = 3
        self.app.config["API_RATE_WINDOW"] = 60
        self.addCleanup(ratelimit.reset_all)

        for _ in range(3):
            self.assertEqual(self.client.get("/api/jobs").status_code, 200)

        blocked = self.client.get("/api/jobs")
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)
        body = blocked.get_json()
        self.assertFalse(body["success"])
        self.assertIn("retry_after_seconds", body["error"])

    def test_sitemap_escapes_company_slugs(self):
        """A slug with an ampersand must not emit malformed XML."""
        with self.app.app_context():
            company = Company(name="Research & Development", slug="research-development")
            db.session.add(company)
            db.session.commit()

        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        import xml.etree.ElementTree as ET

        root = ET.fromstring(sitemap.get_data(as_text=True))
        locs = [e.text for e in root.iter() if e.tag.endswith("loc")]
        self.assertTrue(any("/companies/research-development" in loc for loc in locs))

    def test_icon_sprite_only_ships_icons_the_templates_use(self):
        """The sprite must not regress into shipping the whole icon library."""
        import re
        from pathlib import Path

        sprite_path = Path(__file__).resolve().parents[1] / "app" / "static" / "icons" / "lucide-sprite.svg"
        sprite = sprite_path.read_text(encoding="utf-8")
        ids = set(re.findall(r'<symbol id="([^"]+)"', sprite))
        self.assertLess(len(ids), 200, "sprite looks like the full icon library again")
        # ...and it must be under 60 KB.
        self.assertLess(sprite_path.stat().st_size, 60 * 1024)

    def test_dedup_key_separates_seniority_but_still_merges_true_duplicates(self):
        """An intern posting must not be absorbed into a senior listing.

        Dedup keys on the canonical title, which is identical for every backend
        variant. Without seniority in the key, a brand-new "Backend Engineer
        Intern" listing silently merges into the senior job and disappears from
        the index.
        """
        from app.services.dedup import dedup_hash

        # Distinct roles: same company, same canonical title, different seniority.
        hashes = {
            dedup_hash("Gojek", "Backend Engineer Intern", "Jakarta"),
            dedup_hash("Gojek", "Backend Engineer", "Jakarta"),
            dedup_hash("Gojek", "Senior Backend Engineer", "Jakarta"),
            dedup_hash("Gojek", "Lead Backend Engineer", "Jakarta"),
        }
        self.assertEqual(len(hashes), 4, "seniority is missing from the dedup key")

        # Genuine duplicates still collapse: same role, cosmetic title noise.
        self.assertEqual(
            dedup_hash("Gojek", "Senior Backend Engineer", "Jakarta"),
            dedup_hash("Gojek", "Senior Backend Engineer (m/f/d)", "Jakarta"),
        )
        # ...and a different company or city is still a different job.
        self.assertNotEqual(
            dedup_hash("Gojek", "Backend Engineer", "Jakarta"),
            dedup_hash("Tokopedia", "Backend Engineer", "Jakarta"),
        )
        self.assertNotEqual(
            dedup_hash("Gojek", "Backend Engineer", "Jakarta"),
            dedup_hash("Gojek", "Backend Engineer", "Bandung"),
        )

    def test_job_detail_lists_each_source_only_once(self):
        """A re-posted listing must not render two identical apply links."""
        with self.app.app_context():
            portal = Source(name="JobBoard", engine="api", enabled=True)
            db.session.add(portal)
            db.session.flush()
            for suffix in ("a", "b"):
                db.session.add(JobSource(
                    job_id=self.external_job_id,
                    source_id=portal.id,
                    external_id=f"jobboard-{suffix}",
                    url=f"https://example.test/jobboard/{suffix}",
                    scraped_at=datetime.now(timezone.utc),
                ))
            db.session.commit()

        body = self.client.get(f"/jobs/{self.external_job_id}").get_data(as_text=True)
        self.assertEqual(body.count("Apply on JobBoard"), 1)

    def test_cron_schedules_render_as_prose_not_escaped_cron(self):
        self.assertEqual(describe_cron("0 */6 * * *"), "every 6 hours")
        self.assertEqual(describe_cron("0 */1 * * *"), "hourly")
        self.assertEqual(describe_cron("*/15 * * * *"), "every 15 minutes")
        self.assertEqual(describe_cron("0 3 * * *"), "daily at 3am")
        self.assertEqual(describe_cron("30 14 * * *"), "daily at 2pm:30")
        self.assertEqual(describe_cron("0 0 * * *"), "daily at midnight")
        self.assertEqual(describe_cron(None), "not scheduled")

        # Anything the formatter cannot narrate honestly is passed through rather
        # than guessed at.
        for opaque in ["0 2 * * 1", "0 1 5 * *", "garbage", "0 */0 * * *"]:
            with self.subTest(expression=opaque):
                self.assertEqual(describe_cron(opaque), opaque)

        # And the rendered dashboard must not contain an escaped cron.
        with self.app.app_context():
            db.session.add(Source(name="CronSrc", engine="scrapy", enabled=True,
                                  schedule_cron="0 */6 * * *"))
            db.session.commit()
        self.login("admin@example.com")
        body = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("every 6 hours", body)
        self.assertNotIn("*/6", body)

    def test_auth_pages_link_password_recovery(self):
        login = self.client.get("/auth/login")
        self.assertIn(b"/auth/forgot-password", login.data)
        # The advertised demo account must be the populated one.
        self.assertIn(b"demo@example.com", login.data)

        self.assertEqual(self.client.get("/auth/forgot-password").status_code, 200)


if __name__ == "__main__":
    unittest.main()

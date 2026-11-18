"""Check score parity and the low-memory import boundary."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.services.tfidf_small import similarities


class SmallTfidfTests(unittest.TestCase):
    def test_scores_match_reference(self):
        for corpus, profile in [
            (["Python Python SQL backend API", "Docker platform engineer", "Sales in Jakarta"], "Python SQL engineer"),
            (["The and or", "Résumé café data_engineer 123", "SQL sql api"], "CAFÉ résumé SQL unknown"),
            (["Python SQL", "Java backend", "Python SQL"], "unseen words"),
            (["Python SQL", "Java backend", "Python SQL"], "the and"),
        ]:
            with self.subTest(profile=profile):
                reference = TfidfVectorizer(stop_words="english", max_features=8000, ngram_range=(1, 2))
                matrix = reference.fit_transform(corpus)
                expected = cosine_similarity(reference.transform([profile]), matrix).flatten()
                for actual, expected_score in zip(similarities(corpus, profile), expected):
                    self.assertAlmostEqual(actual, expected_score, places=12)
                pair = reference.fit_transform([corpus[0], profile])
                self.assertAlmostEqual(similarities([corpus[0], profile])[0],
                                       cosine_similarity(pair[0:1], pair[1:2])[0, 0], places=12)

    def test_empty_corpus_and_feature_cap(self):
        for corpus in ([], ["the and", "a !"]):
            with self.assertRaises(ValueError):
                similarities(corpus, "Python")
        self.assertEqual(similarities(["python python sql", "java"], "unknown", max_features=1), [0, 0])
        self.assertEqual(similarities(["python python sql", "java"], "python", max_features=1), [1, 0])

    def test_real_app_does_not_import_scientific_stack(self):
        code = (
            "import sys; from app import create_app; app=create_app('testing'); "
            "from app.services.matching import _similarities; "
            "assert _similarities(['python sql'], 'python')[0] > 0; "
            "assert not any(k.split('.')[0] in {'numpy','scipy','sklearn','pandas'} for k in sys.modules)"
        )
        subprocess.run([sys.executable, "-c", code], check=True,
                       cwd=Path(__file__).resolve().parents[1],
                       env={**os.environ, "MATCHING_BACKEND": "stdlib"})


if __name__ == "__main__":
    unittest.main()

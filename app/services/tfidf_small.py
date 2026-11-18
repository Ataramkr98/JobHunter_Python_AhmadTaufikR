"""Small-corpus TF-IDF without NumPy/SciPy in the web worker.

Raw term counts, English stopwords, unigrams/bigrams, smooth IDF, L2 norms.
At the 8000-term cap, equal-frequency terms use lexical order; NumPy sort
ties can select different equal-frequency terms in the sklearn backend.
"""

from collections import Counter
import math
import re

from app.services.tfidf_stopwords import STOP_WORDS

TOKEN = re.compile(r"(?u)\b\w\w+\b")


def _terms(document):
    tokens = [word for word in TOKEN.findall(document.lower()) if word not in STOP_WORDS]
    counts = Counter(tokens)
    counts.update(" ".join(pair) for pair in zip(tokens, tokens[1:]))
    return counts


def similarities(corpus, profile_text=None, max_features=8000):
    counts = [_terms(document) for document in corpus]
    totals = Counter()
    frequencies = Counter()
    for document in counts:
        totals.update(document)
        frequencies.update(document.keys())
    vocabulary = sorted(totals, key=lambda term: (-totals[term], term))[:max_features]
    if not vocabulary:
        raise ValueError("empty vocabulary")
    idf = {term: math.log((1 + len(corpus)) / (1 + frequencies[term])) + 1
           for term in vocabulary}

    def vector(document):
        weights = {term: count * idf[term] for term, count in document.items() if term in idf}
        norm = math.sqrt(sum(value * value for value in weights.values()))
        return {term: value / norm for term, value in weights.items()} if norm else {}

    vectors = [vector(document) for document in counts]
    if profile_text is None:
        query, candidates = vectors[0], vectors[1:2]
    else:
        query, candidates = vector(_terms(profile_text)), vectors
    return [max(0.0, min(1.0, sum(value * candidate.get(term, 0.0)
                                for term, value in query.items())))
            for candidate in candidates]

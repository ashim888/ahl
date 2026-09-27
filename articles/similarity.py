"""Text-similarity ranking for "Related reading" — used when an editor
hasn't hand-picked Article.related_articles, and to suggest candidates in
the editorial article form.

Method (the standard vector-space model from information retrieval):

1. Each article becomes a bag of terms from its title, keywords, abstract
   and body, with the short fields weighted up (FIELD_WEIGHTS) — a shared
   word in two titles says far more about topic than a shared word deep in
   two bodies. HTML is stripped; English and Nepali stopwords are dropped.
2. Term weights are TF-IDF: sublinear term frequency (1 + ln tf) times
   smoothed inverse document frequency (ln((1 + N) / (1 + df)) + 1), so a
   term common to every article ("health", on a health site) counts for
   little and a distinctive one ("tuberculosis") counts for a lot.
3. Vectors are L2-normalised and compared by cosine similarity, i.e. the
   dot product. Cosine distance is 1 − similarity; for unit vectors the
   Euclidean distance is √(2 − 2·similarity), so ranking by either distance
   gives the same order as ranking by similarity.
4. Candidates below MIN_SIMILARITY are dropped, so an article with nothing
   genuinely related shows fewer (or no) related articles rather than
   unrelated filler.

Pure Python — no numpy/scikit-learn dependency; fine for this site's
corpus size (hundreds to low thousands of articles). The corpus index is
memoised per process and per-article results are cached in Django's cache,
both keyed by a corpus version that changes whenever any published article
is added, edited or unpublished.
"""
import hashlib
import math
import re
from collections import Counter

from django.core.cache import cache
from django.db.models import Count, Max
from django.utils.html import strip_tags

from .models import Article

FIELD_WEIGHTS = {'title': 3, 'keywords': 3, 'abstract': 2, 'body': 1}

# Below this cosine similarity two articles share too little distinctive
# vocabulary to be called related (0 = nothing in common, 1 = identical).
# Tuned on the September 2026 corpus: genuine pairs (two TB-screening
# pieces, two ADHD pieces, a maternal-health study and a letter responding
# to it) scored 0.09–0.31, while incidental overlaps (a cardiac case report
# vs. an ADHD piece, sharing only "adult") scored 0.05–0.065.
MIN_SIMILARITY = 0.08

RESULT_CACHE_TTL = 60 * 60 * 24  # results are also invalidated by corpus version

# Letters (any script) plus the Devanagari block — Devanagari vowel signs
# and viramas are combining marks, not "word" characters to Python's re,
# so without the explicit range Nepali words would be split mid-word.
TOKEN_RE = re.compile(r'[\wऀ-ॿ]+')

ENGLISH_STOPWORDS = frozenset('''
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just may me might
more most must my myself no nor not now of off on once only or other our ours ourselves out over own
per same shall she should so some such than that the their theirs them themselves then there these
they this those through to too under until up upon us very via was we were what when where which
while who whom why will with within without would you your yours yourself yourselves et al ie eg among therefore thus
'''.split())
# Function words only — common *topic* words ("study", "health") are left
# in on purpose: IDF already down-weights whatever the corpus overuses.

NEPALI_STOPWORDS = frozenset('''
र को का की के मा छ छन् हो हुन् थियो थिए ले लाई बाट देखि सम्म पनि नै यो त्यो यी ती यस उक्त गर्न गरेको
गरेका गरी गर्ने गरिएको भएको भएका हुने रहेको रहेका भने भन्ने तथा एवं वा अनि तर एक जुन जस्तै अब अझै
'''.split())

STOPWORDS = ENGLISH_STOPWORDS | NEPALI_STOPWORDS


def _stem(token: str) -> str:
    """Minimal English plural folding ("studies"→"study", "articles"→
    "article") so singular/plural forms count as one term. Deliberately
    not a full stemmer — aggressive stemming conflates medical terms.
    Non-ASCII (e.g. Nepali) tokens are returned unchanged.
    """
    if not token.isascii() or len(token) <= 4:
        return token
    if token.endswith('ies'):
        return token[:-3] + 'y'
    if token.endswith('s') and not token.endswith(('ss', 'us', 'is')):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercased, HTML-stripped, stopword-free terms of `text`."""
    if not text:
        return []
    tokens = []
    for raw in TOKEN_RE.findall(strip_tags(text).lower()):
        token = raw.strip('_')
        if len(token) < 2 or token.isdigit() or token in STOPWORDS:
            continue
        tokens.append(_stem(token))
    return tokens


def weighted_term_counts(title: str, abstract: str, body: str, keywords: list[str]) -> Counter:
    """Field-weighted raw term counts for one article (see FIELD_WEIGHTS)."""
    counts = Counter()
    fields = {
        'title': title, 'abstract': abstract, 'body': body, 'keywords': ' '.join(keywords),
    }
    for field, text in fields.items():
        for token in tokenize(text):
            counts[token] += FIELD_WEIGHTS[field]
    return counts


def _article_counts(article: Article, keyword_names: list[str] | None = None) -> Counter:
    if keyword_names is None:
        keyword_names = [kw.name for kw in article.keyword_tags.all()] if article.pk else []
    return weighted_term_counts(article.title, article.abstract, article.html_content or '', keyword_names)


def _tfidf_vector(counts: Counter, idf: dict[str, float], default_idf: float) -> dict[str, float]:
    """Sublinear-TF × IDF weights, L2-normalised to a unit vector."""
    vector = {term: (1 + math.log(tf)) * idf.get(term, default_idf) for term, tf in counts.items() if tf > 0}
    norm = math.sqrt(sum(w * w for w in vector.values()))
    if not norm:
        return {}
    return {term: w / norm for term, w in vector.items()}


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Dot product of two unit vectors (iterates the smaller one)."""
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(term, 0.0) for term, w in a.items())


def corpus_version() -> str:
    """Changes whenever a published article is added, removed, edited, or
    has its keywords changed (keyword edits go through the article form,
    which saves the article and bumps updated_at).
    """
    stats = Article.objects.filter(status=Article.Status.PUBLISHED).aggregate(
        count=Count('id'), latest=Max('updated_at'),
    )
    raw = f"{stats['count']}:{stats['latest'].isoformat() if stats['latest'] else ''}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class CorpusIndex:
    """TF-IDF vectors for every published article, plus the IDF table
    needed to vectorise an article outside the corpus (e.g. a draft).
    """

    def __init__(self):
        articles = list(
            Article.objects.filter(status=Article.Status.PUBLISHED)
            .only('id', 'title', 'abstract', 'html_content')
            .prefetch_related('keyword_tags'),
        )
        counts_by_id = {a.pk: _article_counts(a) for a in articles}
        n_docs = len(counts_by_id)
        document_frequency = Counter()
        for counts in counts_by_id.values():
            document_frequency.update(counts.keys())

        self.idf = {
            term: math.log((1 + n_docs) / (1 + df)) + 1 for term, df in document_frequency.items()
        }
        # A term no published article uses is maximally distinctive.
        self.default_idf = math.log(1 + n_docs) + 1
        self.vectors = {
            pk: _tfidf_vector(counts, self.idf, self.default_idf) for pk, counts in counts_by_id.items()
        }

    def vector_for(self, article: Article, keyword_names: list[str] | None = None) -> dict[str, float]:
        if article.pk in self.vectors and keyword_names is None:
            return self.vectors[article.pk]
        return _tfidf_vector(_article_counts(article, keyword_names), self.idf, self.default_idf)

    def rank(self, vector: dict[str, float], exclude_ids: set[int]) -> list[tuple[int, float]]:
        scored = [
            (pk, cosine_similarity(vector, other))
            for pk, other in self.vectors.items() if pk not in exclude_ids
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored


# One index per worker process, rebuilt only when the corpus version
# changes — so a burst of article-page views after a publish pays the
# build cost once, not once per page.
_index_memo: dict[str, CorpusIndex] = {}


def get_index(version: str | None = None) -> CorpusIndex:
    version = version or corpus_version()
    index = _index_memo.get(version)
    if index is None:
        index = CorpusIndex()
        _index_memo.clear()
        _index_memo[version] = index
    return index


def similar_articles(
    article: Article, limit: int = 3, min_score: float = MIN_SIMILARITY,
    exclude_ids: set[int] | None = None,
) -> list[tuple[Article, float]]:
    """The `limit` published articles most similar to `article`, as
    (article, cosine similarity) pairs, best first, scores ≥ `min_score`.
    Works for drafts too (vectorised against the published corpus's IDF);
    results are cached only for published articles with no extra excludes.
    """
    exclude = set(exclude_ids or ())
    if article.pk:
        exclude.add(article.pk)

    version = corpus_version()
    cacheable = article.pk and article.status == Article.Status.PUBLISHED and not exclude_ids
    cache_key = f'related:v1:{version}:{article.pk}:{limit}:{min_score}'
    ranked = cache.get(cache_key) if cacheable else None
    if ranked is None:
        index = get_index(version)
        ranked = [
            (pk, round(score, 4))
            for pk, score in index.rank(index.vector_for(article), exclude)[:limit]
            if score >= min_score
        ]
        if cacheable:
            cache.set(cache_key, ranked, RESULT_CACHE_TTL)

    articles_by_id = Article.objects.filter(
        pk__in=[pk for pk, _score in ranked], status=Article.Status.PUBLISHED,
    ).in_bulk()
    return [(articles_by_id[pk], score) for pk, score in ranked if pk in articles_by_id]

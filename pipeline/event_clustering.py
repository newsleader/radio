"""
Lightweight event clustering for NewsLeader.

Groups articles into "events" (same news story) using TF-IDF cosine similarity
and single-linkage clustering. No ML libraries required.

This replaces BERTopic (which needs ~2GB of ML deps) with a fast heuristic
approach that works well for short news headlines and summaries.

BERTopic can be swapped in later by replacing _cluster_articles() while keeping
the same EventCluster interface.

Usage:
    clusters = cluster_articles(articles)
    for cluster in clusters:
        print(f"{cluster.source_count} sources, {len(cluster.articles)} articles")
"""
import math
import re
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)


@dataclass
class EventCluster:
    """A group of articles covering the same news event."""
    articles: list = field(default_factory=list)

    @property
    def source_count(self) -> int:
        """Number of unique sources covering this event."""
        return len({a.source for a in self.articles})


def _tfidf_vector(text: str, doc_freqs: dict[str, int], n_docs: int) -> dict[str, float]:
    """
    TF-IDF bag-of-words vector for a text.
    Uses pre-computed document frequencies for IDF weighting.
    """
    # Tokenize: Korean nouns (≥2 chars) + English words (≥3 chars)
    ko_tokens = re.findall(r'[가-힣]{2,}', text)
    en_tokens = re.findall(r'[A-Za-z]{3,}', text.lower())
    tokens = ko_tokens + en_tokens

    if not tokens:
        return {}

    # TF
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0
    total = len(tokens)
    tf = {k: v / total for k, v in tf.items()}

    # IDF (log smoothed)
    vec: dict[str, float] = {}
    for term, freq in tf.items():
        df = doc_freqs.get(term, 0)
        idf = math.log((n_docs + 1) / (df + 1)) + 1
        vec[term] = freq * idf

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    return sum(a.get(k, 0.0) * v for k, v in b.items())


def cluster_articles(
    articles: list,
    threshold: float = 0.45,
    max_cluster_size: int = 10,
) -> list[EventCluster]:
    """
    Cluster articles by topic similarity using TF-IDF cosine + single-linkage.

    Args:
        articles: list of Article objects (must have .title, .body, .source)
        threshold: cosine similarity threshold for same-cluster assignment
        max_cluster_size: cap cluster size to prevent one story dominating

    Returns:
        List of EventCluster, sorted by source_count desc (most covered first).
    """
    if not articles:
        return []

    # Build document frequency counts
    texts = [f"{a.title} {a.body[:300]}" for a in articles]
    doc_freqs: dict[str, int] = {}
    for text in texts:
        words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', text.lower()))
        for w in words:
            doc_freqs[w] = doc_freqs.get(w, 0) + 1

    n_docs = len(texts)
    vecs = [_tfidf_vector(t, doc_freqs, n_docs) for t in texts]

    # Single-linkage clustering
    cluster_ids = list(range(n_docs))   # initially each article is its own cluster

    for i in range(n_docs):
        for j in range(i + 1, n_docs):
            if cluster_ids[i] == cluster_ids[j]:
                continue
            if _cosine(vecs[i], vecs[j]) >= threshold:
                # Merge j's cluster into i's cluster
                old_cid = cluster_ids[j]
                new_cid = cluster_ids[i]
                cluster_ids = [new_cid if c == old_cid else c for c in cluster_ids]

    # Group by cluster_id
    groups: dict[int, list[int]] = {}
    for idx, cid in enumerate(cluster_ids):
        groups.setdefault(cid, []).append(idx)

    clusters: list[EventCluster] = []
    for cid, idxs in groups.items():
        # Cap cluster size
        idxs = idxs[:max_cluster_size]
        group_articles = [articles[i] for i in idxs]
        clusters.append(EventCluster(articles=group_articles))

    clusters.sort(key=lambda c: c.source_count, reverse=True)
    log.info("event_clustering_done",
             articles=n_docs,
             clusters=len(clusters),
             max_sources=clusters[0].source_count if clusters else 0)
    return clusters

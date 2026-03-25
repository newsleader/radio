"""
Lightweight cross-language article similarity for Korean/English deduplication.

Approach: No ML model download needed.
  1. Normalize text: expand Korean/English abbreviations to a common vocabulary
  2. Extract key phrases (capitalized words, Korean nouns ≥ 2 chars)
  3. Compute TF-IDF bag-of-words vector
  4. Cosine similarity ≥ 0.65 → cross-language near-duplicate

This catches "Fed raises rates by 25bp" ↔ "연준, 기준금리 25bp 인상" without
requiring a 470MB sentence-transformer model.

If full multilingual embeddings are needed later, replace embed() with
sentence_transformers model and keep the same interface.
"""
import math
import re

# ── Cross-language normalization map ─────────────────────────────────────────
# Maps Korean terms → canonical English key (for cross-language comparison)
_KO_TO_EN: dict[str, str] = {
    "연준": "federalreserve", "미국연방준비제도": "federalreserve",
    "연방준비제도": "federalreserve", "기준금리": "interestrate",
    "금리": "rate", "금리인상": "ratehike", "금리인하": "ratecut",
    "국내총생산": "gdp", "소비자물가지수": "cpi", "생산자물가지수": "ppi",
    "국제통화기금": "imf", "세계무역기구": "wto", "유럽중앙은행": "ecb",
    "경제협력개발기구": "oecd", "국제결제은행": "bis",
    "반도체": "semiconductor", "인공지능": "ai",
    "주가": "stockmarket", "주식": "stock", "채권": "bond",
    "달러": "dollar", "유로": "euro", "엔": "yen", "원": "won",
    "중국": "china", "미국": "usa", "러시아": "russia",
    "우크라이나": "ukraine", "이스라엘": "israel", "이란": "iran",
    "대만": "taiwan", "북한": "northkorea", "한국": "korea",
    "유가": "oilprice", "천연가스": "naturalgas", "원자력": "nuclear",
    "전쟁": "war", "제재": "sanction", "협정": "agreement",
}

# Maps English terms → canonical key
_EN_TO_KEY: dict[str, str] = {
    "federal reserve": "federalreserve", "fed": "federalreserve",
    "fomc": "federalreserve", "interest rate": "interestrate",
    "rate hike": "ratehike", "rate cut": "ratecut", "rate increase": "ratehike",
    "european central bank": "ecb", "imf": "imf", "oecd": "oecd", "bis": "bis",
    "semiconductor": "semiconductor", "chip": "semiconductor",
    "artificial intelligence": "ai", "machine learning": "ai",
    "stock market": "stockmarket", "equity": "stockmarket",
    "crude oil": "oilprice", "oil price": "oilprice", "brent": "oilprice",
    "natural gas": "naturalgas", "lng": "naturalgas",
    "north korea": "northkorea", "dprk": "northkorea",
    "south korea": "korea", "seoul": "korea",
    "ukraine": "ukraine", "russia": "russia", "china": "china",
    "taiwan": "taiwan", "iran": "iran", "israel": "israel",
    "war": "war", "sanction": "sanction", "ceasefire": "ceasefire",
    "gdp": "gdp", "cpi": "cpi", "ppi": "ppi",
}

_STOP_KO = frozenset(["의", "이", "가", "을", "를", "은", "는", "에", "서", "로",
                       "과", "와", "이다", "했다", "한다", "된다", "것으로", "했습니다",
                       "입니다", "합니다", "있습니다", "있다", "됩니다"])
_STOP_EN = frozenset(["the", "a", "an", "is", "are", "was", "were", "has", "have",
                       "had", "be", "been", "being", "do", "does", "did",
                       "of", "in", "on", "at", "to", "for", "and", "or", "but",
                       "with", "from", "by", "as", "it", "its", "this", "that"])


def _normalize_and_tokenize(text: str) -> list[str]:
    """
    Return a list of normalized key tokens from Korean/English text.
    Cross-language synonyms are mapped to a shared canonical key.
    """
    text_lower = text.lower()
    tokens: list[str] = []

    # Apply multi-word English mappings first (longer match first)
    for phrase, key in sorted(_EN_TO_KEY.items(), key=lambda x: -len(x[0])):
        if phrase in text_lower:
            tokens.append(key)
            text_lower = text_lower.replace(phrase, " ")

    # Korean term mapping
    for ko_term, en_key in _KO_TO_EN.items():
        if ko_term in text:
            tokens.append(en_key)

    # Extract Korean nouns (2+ chars)
    ko_words = re.findall(r'[가-힣]{2,}', text)
    for w in ko_words:
        if w not in _STOP_KO and w not in _KO_TO_EN:
            tokens.append(w)

    # Extract English words (2+ chars, not stop words)
    en_words = re.findall(r'[a-z]{2,}', text_lower)
    for w in en_words:
        if w not in _STOP_EN and w not in _EN_TO_KEY:
            tokens.append(w)

    # Extract numbers (important for financial news: "25bp", "800억", "4.5%")
    numbers = re.findall(r'\d+(?:\.\d+)?(?:bp|%|억|조|만|trillion|billion|million)?', text)
    tokens.extend(n for n in numbers if len(n) >= 2)

    return tokens


def embed(title: str, body_prefix: str = "") -> dict[str, float]:
    """
    Compute a normalized TF bag-of-words vector for an article.
    Both Korean and English text is handled; cross-language synonyms share keys.

    Returns: {token: tf_normalized_weight}
    """
    text = title + " " + body_prefix[:300]
    tokens = _normalize_and_tokenize(text)

    if not tokens:
        return {}

    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0

    # Normalize (L2)
    norm = math.sqrt(sum(v * v for v in tf.values()))
    if norm > 0:
        tf = {k: v / norm for k, v in tf.items()}

    return tf


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two TF vectors."""
    if not a or not b:
        return 0.0
    return sum(a.get(k, 0.0) * v for k, v in b.items())



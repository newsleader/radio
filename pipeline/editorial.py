"""
Editorial intelligence for NewsLeader.

No LLM calls — pure heuristics.

Features:
  - Keyword-based article categorization
  - Article importance scoring (recency + source tier + breaking signals)
  - EditorialScheduler: topic diversity (prevent category flooding)
  - BreakingNewsDetector: velocity-based breaking news (same topic, 3+ feeds, 30 min)
  - MMR (Maximal Marginal Relevance): diverse article selection
  - Time-of-day programming: category weights by hour (KST)
"""
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Category keywords ─────────────────────────────────────────────────────────

_CATEGORY_KEYWORDS = {
    "finance": [
        "금리", "주가", "경제", "시장", "금융", "달러", "유가", "채권", "주식",
        "Fed", "연준", "ECB", "gdp", "cpi", "inflation", "rate", "stock",
        "market", "bank", "투자", "펀드", "환율", "수출", "무역", "관세",
        "tariff", "trade", "oil", "energy", "crypto", "bitcoin",
    ],
    "tech": [
        "인공지능", "AI", "반도체", "데이터", "소프트웨어", "클라우드",
        "스타트업", "앱", "플랫폼", "칩", "GPU", "LLM", "로봇",
        "tech", "software", "chip", "semiconductor", "startup",
        "microsoft", "google", "apple", "amazon", "meta", "nvidia",
        "openai", "anthropic", "samsung", "tsmc",
    ],
    "geopolitics": [
        "전쟁", "외교", "안보", "군사", "분쟁", "제재", "협정", "조약",
        "NATO", "UN", "이란", "중국", "러시아", "우크라이나", "이스라엘",
        "팔레스타인", "대만", "북한", "미국", "동맹", "핵",
        "war", "sanction", "treaty", "nato", "military", "strike",
        "attack", "missile", "nuclear", "ceasefire", "conflict",
    ],
    "domestic_kr": [
        "한국", "서울", "국내", "정부", "대통령", "국회", "여당", "야당",
        "청와대", "기획재정부", "한국은행", "코스피", "코스닥",
        "korea", "seoul", "korean",
    ],
    "energy": [
        "에너지", "석유", "천연가스", "원자력", "태양광", "풍력", "탄소",
        "climate", "carbon", "lng", "opec", "renewable", "nuclear",
        "유전", "정유", "배터리", "전기차",
    ],
    "human_interest": [
        "문화", "스포츠", "생활", "건강", "사회", "인물", "예술",
        "education", "health", "science", "space", "sport",
        "연구", "발견", "개발", "우주", "기후", "환경",
    ],
}

# ── Source credibility tiers ─────────────────────────────────────────────────

_SOURCE_TIER: dict[str, float] = {
    # Wire services / national agencies — highest authority
    "AP World": 1.0, "AP Business": 1.0, "AP Technology": 1.0,
    "Yonhap English": 1.0, "연합뉴스경제": 1.0,
    # Major public broadcasters
    "BBC World": 0.95, "BBC Business": 0.95, "BBC Technology": 0.90,
    "BBC Science": 0.90, "NPR World": 0.90, "NPR Business": 0.90,
    "NPR Technology": 0.90, "NHK World": 0.88,
    "DW World": 0.88, "DW Business": 0.88, "DW Asia": 0.85,
    "France 24": 0.85, "France 24 Business": 0.85,
    "Al Jazeera": 0.82,
    # Korean domestic
    "매일경제": 0.85, "한국경제": 0.85, "조선비즈": 0.82,
    "서울경제": 0.80, "SBS뉴스": 0.80,
    "Korea Herald Business": 0.78, "Korea Herald World": 0.78,
    "Korea Times": 0.75, "KBS World": 0.80,
    # Financial / specialized
    "CNBC Business": 0.82, "CNBC Technology": 0.80, "CNBC World": 0.80,
    "MarketWatch": 0.78, "Fortune Finance": 0.75,
    "Guardian Business": 0.82, "Guardian World": 0.82,
    "Guardian Tech": 0.80,
    # Multilateral institutions
    "IMF News": 0.95, "IMF Blog": 0.90, "Federal Reserve": 1.0,
    "ECB": 0.95, "OECD": 0.90, "BIS Research": 0.90,
    "EIA Energy": 0.88, "한국은행": 1.0,
    # Tech
    "TechCrunch": 0.75, "Ars Technica": 0.78, "Wired": 0.75,
    "The Verge": 0.72, "MIT Tech Review": 0.82, "VentureBeat": 0.70,
    "IEEE Spectrum": 0.85, "Hacker News": 0.55,
    # Think tanks
    "Brookings": 0.78, "CFR": 0.78, "Foreign Affairs": 0.78,
    # Asian
    "Nikkei Asia": 0.88, "SCMP Business": 0.80, "SCMP Technology": 0.78,
    "SCMP Asia": 0.80,
    # Korean tech
    "전자신문": 0.78, "ZDNet Korea": 0.72,
}

_DEFAULT_TIER = 0.65

# ── Breaking news keywords ────────────────────────────────────────────────────

_BREAKING_KW = re.compile(
    r'속보|긴급|단독|사망|부상|폭발|화재|지진|테러|충돌|선언|계엄|비상|'
    r'breaking|urgent|alert|crash|explosion|attack|dead|killed|emergency|'
    r'resignation|arrested|collapse|ceasefire|strike',
    re.IGNORECASE,
)

# ── Max segments per category per hour ───────────────────────────────────────

_MAX_PER_HOUR: dict[str, int] = {
    "finance": 30,
    "tech": 25,
    "geopolitics": 30,
    "domestic_kr": 25,
    "energy": 20,
    "human_interest": 20,
    "general": 35,
}


# ── Public API ────────────────────────────────────────────────────────────────

def categorize_article(title: str, source: str) -> str:
    """Keyword-based category — no LLM needed."""
    text = (title + " " + source).lower()
    scores: dict[str, int] = {}
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw.lower() in text)
    best_cat = max(scores, key=lambda c: scores[c])
    if scores[best_cat] > 0:
        return best_cat
    # Source-based fallback
    src_lower = source.lower()
    if any(k in src_lower for k in ["finance", "market", "economy", "bank", "fed", "ecb", "imf", "eia"]):
        return "finance"
    if any(k in src_lower for k in ["tech", "wired", "verge", "ars", "ieee", "hacker"]):
        return "tech"
    if any(k in src_lower for k in ["world", "global", "international", "aljazeera", "dw", "france24"]):
        return "geopolitics"
    if any(k in src_lower for k in ["korea", "한국", "연합", "매일", "한국경제", "서울"]):
        return "domestic_kr"
    return "general"


def score_article(article, cluster_size: int = 1) -> float:
    """
    Score article importance for broadcast priority.
    Higher = more important = process sooner.
    """
    score = 0.0

    # 1. Recency (0–3 points, exponential decay over 4 hours)
    #    Half-life ~90 min: articles published 90 min ago score ~1.5 pts, 3h ago ~0.75 pts
    if article.published:
        try:
            from email.utils import parsedate_to_datetime
            pub = parsedate_to_datetime(article.published)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - pub).total_seconds() / 60
            score += 3.0 * math.exp(-age_min / 90.0)
        except Exception:
            pass

    # 2. Breaking news keywords in title (0–4 points)
    kw_hits = len(_BREAKING_KW.findall(article.title))
    score += min(kw_hits * 2.0, 4.0)

    # 3. Source credibility (0–2 points)
    tier = _SOURCE_TIER.get(article.source, _DEFAULT_TIER)
    score += tier * 2.0

    # 4. Cross-feed cluster size (0–3 points)
    score += min((cluster_size - 1) * 0.75, 3.0)

    # 5. Body length (0–1 point)
    if len(article.body) > 500:
        score += 1.0
    elif len(article.body) > 200:
        score += 0.5

    return score


def is_breaking(title: str) -> bool:
    """Return True if the title contains breaking news signals."""
    return bool(_BREAKING_KW.search(title))


# ── Editorial Scheduler ───────────────────────────────────────────────────────

class EditorialScheduler:
    """
    Prevents category flooding — e.g. 10 Iran war articles in a row.

    Rules:
    - Max N articles per category per hour
    - Never two consecutive articles of the same category (unless breaking)
    """

    def __init__(self) -> None:
        # {category: [timestamp, ...]}
        self._broadcast_times: dict[str, list] = defaultdict(list)
        self._last_category: Optional[str] = None

    def should_broadcast(self, category: str, is_breaking_news: bool = False) -> bool:
        """Return True if this category still has quota and isn't consecutive."""
        # Breaking news always gets through
        if is_breaking_news:
            return True

        # Prune old timestamps
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=1)
        self._broadcast_times[category] = [
            t for t in self._broadcast_times[category] if t > cutoff
        ]

        # Consecutive same-category check
        if category == self._last_category:
            return False

        # Hourly quota check
        max_allowed = _MAX_PER_HOUR.get(category, 5)
        return len(self._broadcast_times[category]) < max_allowed

    def record_broadcast(self, category: str) -> None:
        self._broadcast_times[category].append(datetime.now(timezone.utc))
        self._last_category = category


# ── Breaking News Detector ────────────────────────────────────────────────────

class BreakingNewsDetector:
    """
    Velocity-based breaking news detection.

    Signal: same topic from ≥ min_sources within 30 minutes AND keyword signal.
    - velocity-only (no keywords) requires ≥ 4 sources (not 3) to reduce false positives
    - Each unique story is only flagged as breaking ONCE to prevent double-broadcast
    """

    def __init__(self, window_minutes: int = 30, min_sources: int = 3) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._min_sources = min_sources
        # [(datetime, title, source), ...]
        self._recent: list[tuple] = []
        # Titles already flagged as breaking this session (avoid double-priority)
        self._already_flagged: set[str] = set()

    def _keywords(self, title: str) -> frozenset:
        STOP = {
            "the", "a", "an", "is", "are", "was", "were", "has", "have",
            "of", "in", "on", "at", "to", "for", "and", "or", "but", "with",
            "의", "이", "가", "을", "를", "은", "는", "에", "서", "로",
            "이다", "했다", "한다", "된다",
        }
        words = set(re.sub(r'[^\w\s]', ' ', title.lower()).split())
        return frozenset(w for w in words if w not in STOP and len(w) >= 2)

    def _title_key(self, title: str) -> str:
        """Normalize title for dedup tracking."""
        return re.sub(r'[^\w]', '', title.lower())[:60]

    def check_and_register(self, title: str, source: str) -> bool:
        """
        Register article, return True only if genuinely breaking.
        Each story is only flagged once to prevent the same story being
        priority-queued multiple times from different sources.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - self._window
        self._recent = [(t, tit, src) for t, tit, src in self._recent if t > cutoff]

        keyword_breaking = is_breaking(title)
        new_kw = self._keywords(title)

        # Find sources that covered similar topic recently
        matching_sources: set[str] = set()
        if new_kw:
            for _, past_title, past_source in self._recent:
                past_kw = self._keywords(past_title)
                # Method 1: keyword Jaccard similarity
                keyword_match = bool(past_kw and
                    len(new_kw & past_kw) / len(new_kw | past_kw) >= 0.5)
                # Method 2: NER entity overlap (improves cross-language detection)
                try:
                    from pipeline.ner import entity_overlap_score
                    ner_match = entity_overlap_score(title, past_title) >= 0.4
                except Exception:
                    ner_match = False
                if keyword_match or ner_match:
                    matching_sources.add(past_source)

        self._recent.append((now, title, source))

        # Velocity signal requires more sources when no keyword signal
        velocity_threshold = self._min_sources - 1 if keyword_breaking else self._min_sources + 1
        velocity_breaking = len(matching_sources) >= velocity_threshold

        result = keyword_breaking or velocity_breaking
        if not result:
            return False

        # Dedup: only flag each story once
        key = self._title_key(title)
        if key in self._already_flagged:
            return False   # already priority-queued this story
        self._already_flagged.add(key)

        log.info(
            "breaking_news_detected",
            title=title[:60],
            matching_sources=len(matching_sources),
            keyword_signal=keyword_breaking,
        )
        return True


# Global singletons
editorial_scheduler = EditorialScheduler()
breaking_detector = BreakingNewsDetector()


# ── Time-of-day category weights (KST) ───────────────────────────────────────

# {hour_range: {category: weight_multiplier}}
# Morning (6-9): economic focus (stock market open, business news)
# Midday (9-13): general mix
# Afternoon (13-18): tech + geopolitics
# Evening (18-22): domestic + human interest
# Night (22-6): global (US/Europe markets active)
_TIME_WEIGHTS: list[tuple[range, dict[str, float]]] = [
    (range(6, 9),   {"finance": 1.5, "domestic_kr": 1.3, "tech": 1.0, "geopolitics": 0.9, "human_interest": 0.7}),
    (range(9, 13),  {"finance": 1.2, "tech": 1.1, "geopolitics": 1.1, "domestic_kr": 1.0, "human_interest": 1.0}),
    (range(13, 18), {"tech": 1.3, "geopolitics": 1.2, "finance": 1.0, "energy": 1.1, "domestic_kr": 0.9}),
    (range(18, 22), {"domestic_kr": 1.3, "human_interest": 1.2, "geopolitics": 1.1, "finance": 0.9}),
    (range(22, 24), {"geopolitics": 1.3, "finance": 1.2, "tech": 1.1, "energy": 1.0}),
    (range(0, 6),   {"geopolitics": 1.3, "finance": 1.2, "tech": 1.0, "energy": 1.0}),
]


def get_time_weight(category: str) -> float:
    """Return a score multiplier for `category` based on current KST hour."""
    kst_hour = datetime.now(timezone(timedelta(hours=9))).hour
    for hour_range, weights in _TIME_WEIGHTS:
        if kst_hour in hour_range:
            return weights.get(category, 1.0)
    return 1.0


# ── MMR (Maximal Marginal Relevance) article selection ───────────────────────

def _text_vector(text: str) -> dict[str, float]:
    """Simple TF bag-of-words vector (Korean + English words ≥ 2 chars)."""
    words = re.findall(r'[가-힣]{2,}|[A-Za-z]{2,}', text.lower())
    vec: dict[str, float] = {}
    for w in words:
        vec[w] = vec.get(w, 0.0) + 1.0
    # Normalize
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two TF vectors."""
    return sum(a.get(k, 0.0) * v for k, v in b.items())


def mmr_select(
    articles: list,
    scores: list[float],
    k: int,
    lambda_: float = 0.6,
) -> list:
    """
    Maximal Marginal Relevance selection.

    Balances relevance (score) and diversity (low similarity to already-selected).

    Args:
        articles: list of Article objects
        scores: relevance score per article (same order)
        k: number to select
        lambda_: weight between relevance (1.0) and diversity (0.0)

    Returns:
        Selected articles in MMR order (most important first).
    """
    if not articles:
        return []

    k = min(k, len(articles))
    vecs = [_text_vector(f"{a.title} {a.body[:500]}") for a in articles]

    # Normalize scores to [0, 1]
    max_s = max(scores) or 1.0
    norm_scores = [s / max_s for s in scores]

    selected_idx: list[int] = []
    remaining = set(range(len(articles)))

    for _ in range(k):
        best_idx = -1
        best_mmr = float("-inf")

        for i in remaining:
            relevance = norm_scores[i]
            if not selected_idx:
                redundancy = 0.0
            else:
                redundancy = max(_cosine(vecs[i], vecs[j]) for j in selected_idx)

            mmr = lambda_ * relevance - (1 - lambda_) * redundancy
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i

        if best_idx == -1:
            break
        selected_idx.append(best_idx)
        remaining.discard(best_idx)

    return [articles[i] for i in selected_idx]

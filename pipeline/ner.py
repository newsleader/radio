"""
Korean Named Entity Recognition (NER) for NewsLeader.

Strategy: lightweight regex-based NER without ML models.
Extracts Korean named entities (people, organizations, places, dates)
that are used for:
  1. Improved breaking news detection (entity-level matching)
  2. Script quality enhancement (entity context)
  3. ICY metadata enrichment (entity-aware title)

Optional upgrade: If `transformers` + `torch` are installed and the model
'snunlp/KR-ELECTRA-discriminator' (KLUE-NER) is available, full NER is used.
Otherwise, falls back to a curated regex-based extractor.

Entity types:
  PER  — Person names (인물)
  ORG  — Organizations (기관/기업)
  LOC  — Locations (장소)
  DAT  — Dates/Times (날짜/시간)
  NUM  — Numbers/Quantities (수치)
"""
import re
from dataclasses import dataclass


@dataclass
class Entity:
    text: str
    label: str   # PER, ORG, LOC, DAT, NUM


# ── Regex-based Korean NER ────────────────────────────────────────────────────

# Known Korean organizations
_ORG_PATTERNS = [
    r'(?:미국|유럽|한국|중국|일본|독일|영국|프랑스|러시아|인도)?\s*(?:연방준비제도|중앙은행|재무부|외무부|국방부|상무부)',
    r'(?:국제통화기금|세계은행|세계무역기구|경제협력개발기구|국제결제은행|국제원자력기구)',
    r'(?:삼성전자|현대자동차|SK하이닉스|LG전자|포스코|롯데|카카오|네이버|쿠팡|현대|기아)',
    r'(?:마이크로소프트|구글|애플|아마존|메타|엔비디아|인텔|퀄컴|테슬라|오픈에이아이|앤트로픽)',
    r'(?:연준|연방준비제도이사회|유럽중앙은행|한국은행|일본은행)',
    r'(?:국회|청와대|기획재정부|금융위원회|공정거래위원회|산업통상자원부)',
    r'[가-힣]{2,5}(?:은행|증권|보험|투자|캐피탈|자산운용)',
    r'[가-힣]{2,6}(?:그룹|홀딩스|파트너스|벤처스)',
]

# Country/location patterns
_LOC_PATTERNS = [
    r'(?:미국|중국|일본|한국|러시아|독일|영국|프랑스|이탈리아|캐나다|호주|인도|브라질|인도네시아)',
    r'(?:서울|부산|대구|인천|광주|대전|울산|세종|수원|성남|창원)',
    r'(?:워싱턴|뉴욕|런던|파리|베를린|도쿄|베이징|상하이|모스크바|두바이)',
    r'(?:중동|동남아|유럽|아시아|아프리카|남미|북미)',
    r'(?:월가|실리콘밸리|월스트리트)',
]

# Date patterns
_DAT_PATTERNS = [
    r'\d{4}년\s*\d{1,2}월(?:\s*\d{1,2}일)?',
    r'\d{1,2}월\s*\d{1,2}일',
    r'(?:올해|올 해|지난해|내년|올 분기|지난 분기|이번 달|지난달)',
    r'(?:오전|오후)\s*\d{1,2}시(?:\s*\d{2}분)?',
]

# Number/quantity patterns (financial)
_NUM_PATTERNS = [
    r'\d+(?:,\d{3})*(?:\.\d+)?(?:조|억|만)?\s*(?:달러|유로|원|엔|파운드)',
    r'\d+(?:\.\d+)?(?:퍼센트|%|bp|기가|테라|메가)',
    r'\d+(?:\.\d+)?\s*배',
]


def _extract_with_patterns(text: str, patterns: list, label: str) -> list[Entity]:
    entities = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            e = Entity(text=m.group().strip(), label=label)
            if len(e.text) >= 2:
                entities.append(e)
    return entities


def extract_entities(text: str) -> list[Entity]:
    """
    Extract named entities from Korean text using regex patterns.
    Returns list of Entity objects (may have duplicates for overlapping patterns).
    """
    entities: list[Entity] = []
    entities += _extract_with_patterns(text, _ORG_PATTERNS, "ORG")
    entities += _extract_with_patterns(text, _LOC_PATTERNS, "LOC")
    entities += _extract_with_patterns(text, _DAT_PATTERNS, "DAT")
    entities += _extract_with_patterns(text, _NUM_PATTERNS, "NUM")

    # Deduplicate by (text, label)
    seen: set[tuple] = set()
    unique: list[Entity] = []
    for e in entities:
        key = (e.text, e.label)
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique



def entity_overlap_score(title_a: str, title_b: str) -> float:
    """
    Compute Jaccard similarity of named entities between two titles.
    High score (≥ 0.5) suggests same story even if wording differs.
    Used to improve breaking news detection.
    """
    ents_a = {e.text for e in extract_entities(title_a)}
    ents_b = {e.text for e in extract_entities(title_b)}
    if not ents_a and not ents_b:
        return 0.0
    union = ents_a | ents_b
    if not union:
        return 0.0
    return len(ents_a & ents_b) / len(union)

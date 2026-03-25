"""
Rule-based QA for generated Korean radio scripts.

No LLM calls — pure regex/heuristic checks.
Used to catch format violations and LLM refusals before TTS synthesis.
"""
import re
from dataclasses import dataclass


@dataclass
class QAResult:
    passed: bool
    issues: list[str]     # hard failures (block broadcast)


# ── LLM refusal / meta-commentary patterns ───────────────────────────────────
_REFUSAL_PATTERNS = [
    r'죄송합니다',
    r'도와드릴\s*수\s*없',
    r'제공할\s*수\s*없',
    r'작성하기\s*어렵',
    r'부적절한\s*내용',
    r'저는\s*인공지능',
    r'AI\s*어시스턴트',
    r'언어\s*모델',
    r'As an AI',
    r"I'm sorry",
    r'I cannot',
    r'위\s*기사를\s*기반으로',
    r'아래와\s*같이\s*작성',
    r'다음과\s*같이\s*작성',
    r'\[주의\]|\[경고\]|\[참고\]|\[편집자\s*주\]',
]

_REFUSAL_RE = re.compile('|'.join(_REFUSAL_PATTERNS), re.IGNORECASE)


def detect_refusal(script: str) -> bool:
    """Return True if script looks like an LLM refusal or meta-commentary."""
    if _REFUSAL_RE.search(script):
        return True
    # Structural check: a real 8-11 sentence script has many sentence endings
    sentence_endings = re.findall(r'(?:습니다|입니다|됩니다|겠습니다|합니다|니다)\s*[.!?]', script)
    return len(sentence_endings) < 3


# ── Main QA function ──────────────────────────────────────────────────────────

def qa_script(script: str, source_body: str = "") -> QAResult:
    """
    Run rule-based QA on a generated Korean radio script.
    Returns QAResult with passed=False if any hard issue is found.
    """
    issues: list[str] = []

    # 1. Opening phrase
    if "다음 소식입니다." not in script[:60]:
        issues.append(f"OPENING_WRONG: '{script[:30]}'")

    # 2. Closing phrase
    if not re.search(r'이상으로.{1,60}소식이었습니다', script):
        issues.append("CLOSING_MISSING")

    # 3. Word count (target 170-210 어절; < 120 is clearly a failure)
    wc = len(script.split())
    if wc < 120:
        issues.append(f"WORD_COUNT_{wc}_too_short_min_120")

    # 4. Detect JSON extraction failure
    _JSON_KEYWORDS = {"script", "topic", "word_count", "false", "true", "null"}
    json_leakage = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', script)
                    if w.lower() in _JSON_KEYWORDS]
    if json_leakage:
        issues.append(f"JSON_LEAKAGE: {json_leakage[:5]}")

    # 5. No URL / HTML / markdown
    if re.search(r'https?://|<[^>]+>|\*\*|#{1,6}\s', script):
        issues.append("MARKUP_FOUND")

    # 6. No LLM refusal / meta-commentary
    if detect_refusal(script):
        issues.append("LLM_REFUSAL_DETECTED")

    # 7. No list-format markers
    list_markers = re.findall(r'첫째|둘째|셋째|넷째|①|②|③|④|△\s|\d+\.\s', script)
    if list_markers:
        issues.append(f"LIST_FORMAT: {list_markers[:3]}")

    # 8. No brackets (prompt bans them; TTS reads them awkwardly)
    if re.search(r'[()【】\[\]{}「」]', script):
        issues.append("BRACKETS_FOUND")

    return QAResult(passed=len(issues) == 0, issues=issues)

"""
Korean radio TTS script generator — OpenAI-compatible LLM backend.

LLM output is validated via a Pydantic model (structured output).
The LLM is asked to return JSON; script text is extracted and QA-checked.
"""
import json
import os
import re
from typing import Optional

import structlog
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from config import config
from pipeline.fetcher import Article


# ── Pydantic structured output model ────────────────────────────────────────

class NewsScriptResponse(BaseModel):
    """Structured output from LLM for a Korean radio news script."""
    script: str = Field(..., description="완성된 라디오 대본 (순수 한국어 텍스트)")
    topic: str = Field(default="", description="핵심 주제 한 줄 (ICY 메타데이터용, 30자 이내)")
    word_count: int = Field(default=0, description="대본의 어절 수")

    @field_validator("script")
    @classmethod
    def script_strip(cls, v: str) -> str:
        v = v.strip()
        # Strip bracket characters (prompt bans them; TTS reads them awkwardly)
        v = re.sub(r'[()【】\[\]{}「」]', '', v)
        v = re.sub(r' {2,}', ' ', v)
        return v


def _extract_json_from_llm(raw: str) -> Optional[NewsScriptResponse]:
    """
    Extract and validate JSON from LLM output.
    Handles ```json fences, bare JSON objects, and common LLM malformed JSON.
    Falls back to regex extraction if json.loads fails.
    """
    content = raw
    fence = re.search(r'```(?:json)?\s*', raw)
    if fence:
        content = raw[fence.end():]
        # Remove closing fence
        content = re.sub(r'\n?```\s*$', '', content, flags=re.MULTILINE)

    start = content.find('{')
    end = content.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None

    json_str = content[start:end + 1]

    # Attempt 1: direct json.loads
    try:
        data = json.loads(json_str)
        return NewsScriptResponse.model_validate(data)
    except Exception:
        pass

    # Attempt 2: fix unescaped literal newlines/tabs inside quoted strings
    try:
        fixed = re.sub(
            r'"((?:[^"\\]|\\.)*)"',
            lambda m: '"' + m.group(1).replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"',
            json_str,
        )
        data = json.loads(fixed)
        return NewsScriptResponse.model_validate(data)
    except Exception:
        pass

    # Attempt 3: regex-extract the "script" field value directly
    m = re.search(r'"script"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str, re.DOTALL)
    if m:
        script_text = m.group(1).replace('\\n', '\n').replace('\\"', '"').strip()
        if len(script_text.split()) >= 20:
            try:
                return NewsScriptResponse(script=script_text, topic="", word_count=0)
            except Exception:
                pass

    log.debug("json_extraction_failed", preview=json_str[:120])
    return None

log = structlog.get_logger(__name__)


def _call_llm_api(prompt: str) -> str:
    """Call any OpenAI-compatible LLM endpoint (Ollama, OpenAI, Together, etc.)."""
    base_url = os.environ.get("LLM_BASE_URL", config.LLM_BASE_URL)
    model    = os.environ.get("LLM_MODEL",    config.LLM_MODEL)
    api_key  = os.environ.get("LLM_API_KEY",  config.LLM_API_KEY)

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=300)
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.75,
        max_tokens=4096,   # required for thinking models (qwen3.5 etc.) — thinking eats tokens first
        stream=True,
    )
    chunks = []
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            chunks.append(delta)
    return "".join(chunks).strip()

# ── 시스템 프롬프트 ──────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """당신은 20년 경력의 KBS 라디오 뉴스 앵커입니다.
주어진 기사를 바탕으로 라디오 청취자를 위한 뉴스 대본을 작성합니다.
이 대본은 TTS(음성합성)로 읽힙니다. 눈이 아닌 귀를 위한 글입니다.

[필수 형식]
- 반드시 "다음 소식입니다."로 시작
- 반드시 "이상으로 [구체적 주제] 소식이었습니다."로 마무리
- 분량: 170~210 어절, 8~11문장

[문장 구조 — TTS 핵심]
- 문장 하나당 어절 최대 20개 — 초과 시 반드시 분리
- 짧은 문장(5~10어절)과 중간 문장(12~18어절)을 교대 배치
- 핵심 사실 → 짧게, 맥락·인용·배경 → 중간 길이
- 긴 관형절 연속 금지 — 두 문장으로 분리

[구두점 = 호흡 제어]
- 숨 쉬는 자리에 쉼표 삽입 (문법 여부 무관)
- 전환 표현 뒤 항상 쉼표: "한편,", "이에 따라,", "같은 날,"
- 긴 주어부 뒤 쉼표: "기획재정부는, 이번 결정이..."
- 출처·인용 앞 쉼표: "회사 측에 따르면, ..."

[문장 어미 다양화 — 단조 방지]
- 모든 문장을 "-습니다"로만 끝내는 것 금지
- 사실: "-습니다", "-했습니다"
- 인용: "-고 밝혔습니다", "-이라고 전했습니다", "-이라고 설명했습니다"
- 분석: "-것으로 보입니다", "-이라는 분석입니다", "-것으로 풀이됩니다"
- 예정: "-예정입니다", "-방침입니다", "-계획입니다"
- 상황: "-한 상황입니다", "-것으로 알려졌습니다", "-것으로 나타났습니다"

[출처·인용 배치]
- 출처는 반드시 문장 앞에: "A에 따르면, ..." / "B는, ...라고 밝혔습니다"
- 문장 끝 출처 표기 금지: "...라고 A가 말했다" (X)

[번역·표기]
- 외신은 완전한 한국어로 번역
- 고유명사·약어는 한국어 발음 표기만: Fed → "연준", ECB → "유럽중앙은행", OpenAI → "오픈에이아이"
- 약어 첫 등장 시 전체 명칭 사용, 이후 단축 표현 가능
- 한글·영어 혼재 금지: "AI 기업" (X) → "인공지능 기업" (O)

[숫자·단위]
- 핵심이 아닌 수치는 반올림: "3.547%" → "약 3.5퍼센트", "1조 2,345억" → "약 1조 2천억"
- 단위 필수: "$1.2B" → "12억 달러", "€500M" → "5억 유로", "3.5%" → "3점 5퍼센트"
- 시간 범위: "9시-11시" → "9시부터 11시까지"
- 예외: 선거 결과·공식 수치·판결은 정확하게

[날짜·시간]
- "today/오늘" → 구체적 월·일 (발행 시각 기준)
- "yesterday/어제" → 전날 날짜
- 외국 시각 → 한국시간 환산: "9 AM EST" → "한국시간 오후 11시"

[절대 금지]
- 괄호 전면 금지: (), [], {} — 어떤 내용도 괄호 안에 넣지 말 것
- 슬래시(/), 하이픈(-) 단어 연결 금지 → 말로 대체
- 나열 구조 금지: "첫째/둘째", "△항목", "다음과 같습니다:" → 각각 별도 문장으로
- 한 문장에 3개 이상 항목 나열 금지
- 피동형 남용 금지: -되다/-어지다 → 가능하면 능동형으로
- 문어체 접속사 금지: "함으로써", "에 있어서", "의 일환으로" → "-해서", "-에서", "-위해"
- URL, HTML 태그, 마크다운, 이모지, 특수문자, 제목, 출처 표시 금지
- 순수 한국어 텍스트만 출력

[좋은 예시]
다음 소식입니다. 미국 마이크로소프트가, 올해 안에 인공지능 데이터센터 확충에 800억 달러를 투자한다고 밝혔습니다. 우리 돈으로 약 116조 원 규모입니다. 이는 지난해 투자액의 두 배 수준으로, 인공지능 인프라 경쟁이 새로운 국면에 접어들었다는 평가가 나옵니다. 마이크로소프트 측에 따르면, 이번 투자는 미국과 캐나다, 유럽 전역의 데이터센터를 대상으로 합니다. 수만 개의 일자리 창출도 기대되는 상황입니다. 사티아 나델라 최고경영자는, "인공지능이 향후 10년간 산업 생산성을 근본적으로 바꿀 것"이라고 설명했습니다. 업계에서는 이번 발표가 구글, 아마존, 메타 등 경쟁사의 추가 투자를 촉발할 것으로 보입니다. 마이크로소프트는 오픈에이아이와의 협력을 강화해 기업용 인공지능 서비스도 확대할 방침입니다. 이상으로 마이크로소프트 인공지능 투자 소식이었습니다.

[출력 형식]
반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트 금지.
```json
{
  "script": "다음 소식입니다. ...(완성된 대본)... 이상으로 ...소식이었습니다.",
  "topic": "마이크로소프트 인공지능 투자",
  "word_count": 185
}
```"""

_USER_TEMPLATE = """아래 기사를 한국어 라디오 뉴스 대본으로 작성하세요.
170~210 어절, 배경·원인·수치·인용·전망을 모두 담되 반복 없이 작성하세요.

[방송 시각: {kst_now} KST]
[기사 발행: {pub_kst}]
→ "today/오늘/yesterday/어제" 등 상대적 시간 표현은 위 발행 시각 기준으로 구체적 날짜·시각으로 변환

출처: {source}
제목: {title}

기사 내용:
{body}"""


def _fmt_kst(dt) -> str:
    from datetime import timezone, timedelta
    kst = dt.astimezone(timezone(timedelta(hours=9)))
    return kst.strftime("%Y년 %m월 %d일 %p %I시 %M분").replace("AM", "오전").replace("PM", "오후")


def _parse_published(raw: str):
    if not raw:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        pass
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def generate_minimal_fallback(article: Article) -> str:
    """
    Zero-LLM fallback: build a minimal 2-sentence broadcast from article title.
    Used when LLM fails or produces a refusal/invalid script.
    """
    source = article.source or "외신"
    title = article.title.strip().rstrip(".")
    return (
        f"다음 소식입니다. "
        f"{source}에 따르면, {title}. "
        f"이상으로 {source} 소식이었습니다."
    )


def _call_llm(prompt: str, article: Article) -> Optional[str]:
    """Call the configured LLM endpoint. Returns raw output or None on failure."""
    from monitoring.health import increment

    try:
        result = _call_llm_api(prompt)
        log.info("llm_used", model=os.environ.get("LLM_MODEL", config.LLM_MODEL),
                 title=article.title[:60])
        return result
    except Exception as exc:
        log.warning("llm_failed", error=str(exc), title=article.title[:60])
        increment("llm_errors")
        return None


def _build_retry_feedback(issues: list, failed_script: str) -> str:
    """Build an appended prompt section that tells the LLM what went wrong."""
    parts = ["\n\n[이전 시도 QA 실패 — 다시 작성하세요]"]
    word_count = len(failed_script.split())
    for issue in issues:
        if "WORD_COUNT" in issue:
            needed = 170 - word_count
            parts.append(
                f"- 어절 수 부족: 이전 대본은 {word_count}어절 (목표 170~210어절, {needed}어절 부족). "
                "다음을 추가하세요: 배경·원인(왜 이 일이 일어났나), "
                "숫자·규모(구체적 수치), 전문가 인용 또는 당사자 입장, "
                "향후 전망 또는 영향. 반드시 8문장 이상 작성하세요."
            )
        elif issue == "CLOSING_MISSING":
            parts.append(
                "- 마무리 문구 누락: 반드시 '이상으로 [구체적 주제] 소식이었습니다.'로 끝내세요."
            )
        elif "LIST_FORMAT" in issue:
            # Extract the detected markers for a more targeted message
            import re as _re
            found = _re.search(r'LIST_FORMAT: (.+)', issue)
            detected = found.group(1) if found else "'첫째/둘째/셋째'"
            parts.append(
                f"- 나열 구조 절대 금지: {detected} 표현이 감지되었습니다. "
                "'첫째', '둘째', '셋째', '넷째', '①②③④', '△' 단어를 절대 사용하지 마세요. "
                "나열 대신 접속사를 사용하세요: "
                "'셋째, X 프로그램이 있습니다' → '또한 X 프로그램도 마련되어 있습니다'"
            )
        elif issue == "OPENING_WRONG":
            parts.append(
                "- 첫 문장 오류: 반드시 '다음 소식입니다.'로 시작하세요."
            )
    return "\n".join(parts)


def generate_script(article: Article, is_breaking: bool = False) -> Optional[tuple]:
    """
    Generate a Korean radio TTS script via the configured LLM.
    Returns (script, topic) tuple, or None on failure.
    topic is the short Korean topic string for 'Now Playing' display (may be empty string).
    Runs QA validation; retries once on failure; uses minimal fallback on refusal.

    is_breaking: lower word floor to 100 (breaking news often has thin source material;
    retry prompt causes the model to generate even shorter scripts on thin articles)
    """
    from datetime import datetime, timezone, timedelta
    from pipeline.script_qa import qa_script, detect_refusal
    from monitoring.health import increment

    min_words = 100 if is_breaking else 150

    now_kst = datetime.now(timezone(timedelta(hours=9)))
    kst_now = _fmt_kst(now_kst)
    pub_dt = _parse_published(article.published)
    pub_kst = _fmt_kst(pub_dt) + " KST" if pub_dt else "발행 시각 미상"

    prompt = _USER_TEMPLATE.format(
        kst_now=kst_now,
        pub_kst=pub_kst,
        source=article.source,
        title=article.title,
        body=article.body[:3000],
    )

    script = None
    meta_topic: Optional[str] = None
    current_prompt = prompt

    for attempt in range(2):   # up to 2 LLM attempts
        raw = _call_llm(current_prompt, article)
        if not raw:
            break

        # Check for LLM refusal first
        if detect_refusal(raw):
            log.warning("script_refusal_detected", title=article.title[:60],
                        attempt=attempt + 1)
            increment("scripts_qa_failed")
            # Skip article — minimal fallback produces English title + 20 words,
            # which bypasses QA and airs garbage content on radio
            break

        # Try structured JSON extraction (Pydantic validation)
        structured = _extract_json_from_llm(raw)
        if structured:
            script_text = structured.script
            meta_topic = structured.topic
            log.debug("structured_output_ok",
                      topic=structured.topic, word_count=structured.word_count)
        else:
            # JSON extraction failed — treat raw as plain text (backward compat)
            script_text = re.sub(r'[()【】\[\]{}「」]', '', raw)
            script_text = re.sub(r' {2,}', ' ', script_text)
            log.debug("structured_output_fallback_plain", title=article.title[:60])

        # Run QA on the extracted script text
        qa = qa_script(script_text, article.body, min_words=min_words)
        if qa.passed:
            script = script_text
            break
        else:
            log.warning("script_qa_failed", issues=qa.issues,
                        title=article.title[:60], attempt=attempt + 1)
            increment("scripts_qa_failed")
            if attempt < 1:
                log.info("script_retry", title=article.title[:60])
                # Append QA feedback to prompt so the model corrects the specific issue
                current_prompt = prompt + _build_retry_feedback(qa.issues, script_text)
                continue
            # QA still failing after retry
            # If script_text looks like raw JSON, try extracting "script" field directly
            if script_text.lstrip().startswith(('```', '{')):
                rescued = _extract_json_from_llm(script_text)
                if rescued:
                    log.warning("script_rescued_from_json", title=article.title[:60])
                    script = rescued.script
                    break
            # Don't use script if WORD_COUNT failed — a short script is worse than no script.
            # Allow other minor failures (BRACKETS_FOUND, CLOSING_MISSING) to pass through.
            word_count_failed = any("WORD_COUNT" in issue for issue in qa.issues)
            if not word_count_failed and len(script_text.split()) >= 50:
                log.warning("script_qa_failed_using_anyway", title=article.title[:60])
                script = script_text
            break

    if not script:
        log.error("script_generation_all_failed", title=article.title[:60])
        return None

    increment("scripts_generated")
    word_count = len(script.split())
    # If JSON parsing didn't yield a topic, extract from closing phrase:
    # "이상으로 [topic] 소식이었습니다." → topic
    if not meta_topic:
        m = re.search(r'이상으로\s+(.+?)\s+소식이었습니다', script)
        if m:
            meta_topic = m.group(1).strip()[:40]  # cap at 40 chars for ICY
    topic = meta_topic or ""
    log.info(
        "script_generated",
        title=article.title[:60],
        words=word_count,
        topic=topic,
        script_preview=script[-100:].replace("\n", " "),  # 끝부분 확인용
    )
    log.debug("script_full", content=script)
    return script, topic


def generate_station_id() -> str:
    import random
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    hour = now.hour
    minute = now.minute

    ampm = "오전" if hour < 12 else "오후"
    h = hour % 12 or 12
    time_str = f"{ampm} {h}시" + (f" {minute}분" if minute else "")

    variants = [
        (
            f"지금은 {time_str}입니다. "
            f"뉴스리더 라디오를 청취해 주셔서 감사합니다. "
            f"경제, 기술, 국제 뉴스를 24시간 전해드리는 뉴스리더입니다. "
            f"잠시 후 계속해서 최신 소식을 전해드리겠습니다."
        ),
        (
            f"뉴스리더 라디오입니다. 현재 시각은 {time_str}입니다. "
            f"저희는 세계 각지의 뉴스를 실시간으로 전해드리고 있습니다. "
            f"금융, 기술, 지정학 분야의 심층 보도를 계속해서 들려드리겠습니다."
        ),
        (
            f"{time_str}에 함께해 주셔서 감사합니다. "
            f"지금 들으시는 방송은 뉴스리더 라디오입니다. "
            f"글로벌 경제와 IT 트렌드를 중심으로 24시간 뉴스를 방송합니다. "
            f"청취해 주셔서 감사드립니다."
        ),
        (
            f"뉴스리더입니다. 지금은 {time_str}입니다. "
            f"국내외 주요 소식을 빠르고 정확하게 전달하는 뉴스리더 라디오. "
            f"잠시 후 최신 뉴스로 다시 찾아뵙겠습니다."
        ),
    ]
    return random.choice(variants)

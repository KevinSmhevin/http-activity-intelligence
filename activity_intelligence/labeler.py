import hashlib
from collections import Counter

from anthropic import Anthropic, BadRequestError, NotFoundError
from anthropic.types import ToolParam, ToolUseBlock
from dotenv import load_dotenv

from .models import Confidence, Event, Label, LabelSource, Session

load_dotenv()


_PRIMARY_MODEL = "claude-haiku-4-5-20251001"
_FALLBACK_MODEL = "claude-haiku-4-5"

_BASE_SYSTEM_PROMPT = (
    "You label HTTP-activity sessions for a personal activity-intelligence "
    "tool. Output ONLY via the emit_label tool. The label must describe the "
    "activity using ONLY evidence present in the user message. Prefer short "
    "concrete labels (e.g. 'researching graph databases', 'deep work on "
    "design doc') over generic ones. If the evidence is ambiguous or thin, "
    "set confidence to 'low'."
)

_STRICT_ADDENDUM = (
    " Your previous attempt either fabricated evidence or returned invalid "
    "output. Every string in `evidence` MUST appear in the user message "
    "text. Do not invent hosts or paths."
)

_EMIT_LABEL_TOOL: ToolParam = {
    "name": "emit_label",
    "description": "Emit a grounded label for the activity session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "maxLength": 60,
                "description": "Short, concrete description of the activity.",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
            },
        },
        "required": ["label", "confidence", "evidence"],
    },
}


_PATH_MAX = 60
_DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _truncate(text: str, limit: int = _PATH_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _sorted_counts(counter: Counter, n: int) -> list[tuple[str, int]]:
    # Deterministic ordering: count desc, then key asc — breaks Counter's
    # insertion-order tiebreak which depends on input event order.
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def compress_session(session: Session, events: list[Event]) -> str:
    sections = [
        _format_session_header(session),
        _format_apex_section(events),
        _format_referrer_section(events),
    ]
    return "\n\n".join("\n".join(section) for section in sections if section)


def _format_session_header(session: Session) -> list[str]:
    duration_min = session.duration_seconds / 60.0
    dow = _DAY_NAMES[session.start.weekday()]
    return [
        f"source_app: {session.source_app}",
        f"duration_minutes: {duration_min:.1f}",
        f"event_count: {session.event_count}",
        f"fragmentation_score: {session.fragmentation_score:.2f}",
        f"start: {dow} {session.start.hour:02d}:00 UTC",
    ]


def _format_apex_section(events: list[Event]) -> list[str]:
    apex_counts = Counter(e.apex_domain for e in events)
    lines = ["top apex_domains:"]
    for apex, count in _sorted_counts(apex_counts, 5):
        lines.append(f"  {apex} ({count})")
        lines.extend(_format_paths_for_apex(events, apex))
    return lines


def _format_paths_for_apex(events: list[Event], apex: str) -> list[str]:
    paths = Counter(
        e.path for e in events if e.apex_domain == apex and e.path is not None
    )
    return [
        f"    {_truncate(path)} ({pcount})"
        for path, pcount in _sorted_counts(paths, 3)
    ]


def _format_referrer_section(events: list[Event]) -> list[str]:
    referrers = Counter(e.referrer for e in events if e.referrer is not None)
    if not referrers:
        return []
    lines = ["top referrers:"]
    for ref, rcount in _sorted_counts(referrers, 3):
        lines.append(f"  {_truncate(ref)} ({rcount})")
    return lines


def _call_llm(compressed: str, stricter: bool) -> tuple[str, str, list[str]]:
    response = _invoke_llm_with_fallback(compressed, stricter)
    payload = _extract_emit_label_payload(response)
    return _validate_label_payload(payload)


def _invoke_llm_with_fallback(compressed: str, stricter: bool):
    client = Anthropic()
    system = _BASE_SYSTEM_PROMPT + (_STRICT_ADDENDUM if stricter else "")

    def _create(model: str):
        return client.messages.create(
            model=model,
            max_tokens=256,
            temperature=0,
            system=system,
            tools=[_EMIT_LABEL_TOOL],
            tool_choice={"type": "tool", "name": "emit_label"},
            messages=[{"role": "user", "content": compressed}],
        )

    try:
        return _create(_PRIMARY_MODEL)
    except (NotFoundError, BadRequestError):
        return _create(_FALLBACK_MODEL)


def _extract_emit_label_payload(response) -> dict:
    for block in response.content:
        if isinstance(block, ToolUseBlock) and block.name == "emit_label":
            if not isinstance(block.input, dict):
                raise ValueError(f"emit_label input is not a dict: {block.input!r}")
            return block.input
    raise ValueError("LLM response did not contain an emit_label tool_use block")


def _validate_label_payload(payload: dict) -> tuple[str, str, list[str]]:
    label_text = payload.get("label")
    confidence = payload.get("confidence")
    evidence = payload.get("evidence")

    if not isinstance(label_text, str) or not label_text.strip():
        raise ValueError(f"emit_label label is missing or empty: {label_text!r}")
    if confidence not in ("low", "medium", "high"):
        raise ValueError(f"emit_label confidence is invalid: {confidence!r}")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"emit_label evidence is missing or empty: {evidence!r}")
    if not all(isinstance(e, str) for e in evidence):
        raise ValueError(f"emit_label evidence contains non-strings: {evidence!r}")

    return label_text, confidence, evidence


def validate_grounding(evidence: list[str], compressed: str) -> bool:
    if not evidence:
        return False

    compressed_lower = compressed.lower()
    lines_lower = compressed_lower.splitlines()

    return all(
        _evidence_item_is_grounded(item, compressed_lower, lines_lower)
        for item in evidence
    )


def _evidence_item_is_grounded(
    item: str, compressed_lower: str, lines_lower: list[str]
) -> bool:
    item_lower = item.lower()
    if item_lower in compressed_lower:
        return True
    if "." in item:
        return _domain_token_appears_in_lines(item_lower, lines_lower)
    return False


def _domain_token_appears_in_lines(domain_lower: str, lines_lower: list[str]) -> bool:
    return any(
        token.endswith(domain_lower)
        for line in lines_lower
        for token in line.split()
    )


def label_session(
    session: Session,
    events: list[Event],
    cache: dict[str, Label],
) -> Label:
    compressed = compress_session(session, events)
    cache_key = hashlib.sha256(compressed.encode()).hexdigest()
    if cache_key in cache:
        return cache[cache_key]

    for stricter in (False, True):
        try:
            text, confidence, evidence = _call_llm(compressed, stricter=stricter)
            if not validate_grounding(evidence, compressed):
                raise ValueError("evidence failed grounding")
            result = Label(
                text=text,
                confidence=Confidence(confidence),
                evidence=evidence,
                source=LabelSource.LLM,
            )
            cache[cache_key] = result
            return result
        except Exception:
            continue

    fallback_target = (
        session.dominant_hosts[0][0] if session.dominant_hosts else session.context
    )
    result = Label(
        text=f"Activity on {fallback_target}",
        confidence=Confidence.LOW,
        evidence=[],
        source=LabelSource.FALLBACK,
    )
    cache[cache_key] = result
    return result

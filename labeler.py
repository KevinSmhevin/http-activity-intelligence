import hashlib
from collections import Counter

from anthropic import Anthropic, BadRequestError, NotFoundError
from anthropic.types import ToolParam, ToolUseBlock

from models import Confidence, Event, Label, LabelSource, Session


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
    lines: list[str] = []

    duration_min = session.duration_seconds / 60.0
    dow = _DAY_NAMES[session.start.weekday()]

    lines.append(f"source_app: {session.source_app}")
    lines.append(f"duration_minutes: {duration_min:.1f}")
    lines.append(f"event_count: {session.event_count}")
    lines.append(f"fragmentation_score: {session.fragmentation_score:.2f}")
    lines.append(f"start: {dow} {session.start.hour:02d}:00 UTC")

    apex_counts = Counter(e.apex_domain for e in events)
    top_apex = _sorted_counts(apex_counts, 5)

    lines.append("")
    lines.append("top apex_domains:")
    for apex, count in top_apex:
        lines.append(f"  {apex} ({count})")
        paths = Counter(
            e.path for e in events if e.apex_domain == apex and e.path is not None
        )
        for path, pcount in _sorted_counts(paths, 3):
            lines.append(f"    {_truncate(path)} ({pcount})")

    referrers = Counter(e.referrer for e in events if e.referrer is not None)
    if referrers:
        lines.append("")
        lines.append("top referrers:")
        for ref, rcount in _sorted_counts(referrers, 3):
            lines.append(f"  {_truncate(ref)} ({rcount})")

    return "\n".join(lines)


def _call_llm(compressed: str, stricter: bool) -> tuple[str, str, list[str]]:
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
        response = _create(_PRIMARY_MODEL)
    except (NotFoundError, BadRequestError):
        response = _create(_FALLBACK_MODEL)

    tool_use: ToolUseBlock | None = None
    for block in response.content:
        if isinstance(block, ToolUseBlock) and block.name == "emit_label":
            tool_use = block
            break

    if tool_use is None:
        raise ValueError("LLM response did not contain an emit_label tool_use block")

    payload = tool_use.input
    if not isinstance(payload, dict):
        raise ValueError(f"emit_label input is not a dict: {payload!r}")

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

    for item in evidence:
        item_lower = item.lower()

        if item_lower in compressed_lower:
            continue

        if "." in item:
            if any(
                token.endswith(item_lower)
                for line in lines_lower
                for token in line.split()
            ):
                continue

        return False

    return True


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

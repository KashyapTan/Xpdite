"""Safe extraction of upstream provider errors for user-facing messages."""

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Optional

_REDACTED = "[REDACTED]"
_MAX_MESSAGE_CHARS = 280

_PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "openai-codex": "ChatGPT subscription",
    "openrouter": "OpenRouter",
}

_WRAPPER_PREFIX_RE = re.compile(
    r"^(?:[A-Za-z_][\w.]*?(?:Error|Exception))(?:\s*[:\-]\s*)+",
)

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"([?&](?:api_key|key|token|auth|authorization)=)[^&\s]+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"((?:api[_ -]?key|token|secret|password|authorization)\s*[:=]\s*)"
            r"(['\"]?)[^'\"\s,]+",
            re.IGNORECASE,
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"), _REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), _REDACTED),
)


@dataclass(frozen=True)
class ProviderErrorDetails:
    """Structured provider error details after safe extraction."""

    message: Optional[str]
    status_code: Optional[int]
    provider_code: Optional[str]


def build_provider_error_message(provider: str, exc: BaseException) -> str:
    """Return a safe, user-facing provider error message."""
    details = extract_provider_error_details(exc)
    provider_label = _PROVIDER_LABELS.get(provider.lower(), provider.capitalize())

    if details.message:
        return f"{provider_label} API request failed: {details.message}"

    if details.status_code == 401:
        return (
            f"{provider_label} API request failed: authentication failed. "
            "Check the configured API key."
        )
    if details.status_code == 403:
        return f"{provider_label} API request failed: permission denied."
    if details.status_code == 404:
        return (
            f"{provider_label} API request failed: model or endpoint was not found."
        )
    if details.status_code == 408:
        return f"{provider_label} API request failed: request timed out."
    if details.status_code == 429:
        return (
            f"{provider_label} API request failed: rate limit, quota, or billing "
            "capacity was exhausted."
        )
    if details.status_code is not None and details.status_code >= 500:
        return (
            f"{provider_label} API request failed: provider service is temporarily "
            "unavailable."
        )
    if details.provider_code == "RESOURCE_EXHAUSTED":
        return (
            f"{provider_label} API request failed: provider quota or billing "
            "capacity was exhausted."
        )

    return f"{provider_label} API request failed. See server logs for details."


def extract_provider_error_details(exc: BaseException) -> ProviderErrorDetails:
    """Extract the safest useful message available from a provider exception."""
    status_code = _coerce_int(getattr(exc, "status_code", None))
    provider_code: Optional[str] = None
    message: Optional[str] = None

    for payload in _iter_payload_candidates(exc):
        details = _extract_payload_details(payload)
        if status_code is None and details.status_code is not None:
            status_code = details.status_code
        if provider_code is None and details.provider_code:
            provider_code = details.provider_code
        if message is None and details.message:
            message = details.message
            break

    return ProviderErrorDetails(
        message=_normalize_provider_message(message),
        status_code=status_code,
        provider_code=provider_code,
    )


def _iter_payload_candidates(exc: BaseException):
    seen: set[str] = set()

    def _yield_once(value: Any):
        if value is None:
            return
        if isinstance(value, (bytes, bytearray)):
            marker = bytes(value[:120]).decode("utf-8", errors="ignore")
        else:
            marker = repr(value)[:200]
        key = f"{type(value).__name__}:{marker}"
        if key in seen:
            return
        seen.add(key)
        yield value

    for attr in ("body",):
        yield from _yield_once(getattr(exc, attr, None))

    response = getattr(exc, "response", None)
    if response is not None:
        json_method = getattr(response, "json", None)
        if callable(json_method):
            try:
                yield from _yield_once(json_method())
            except Exception:
                pass

        for attr in ("text", "content"):
            value = getattr(response, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            yield from _yield_once(value)

        yield from _yield_once(getattr(response, "status_code", None))

    for attr in ("message", "litellm_debug_info"):
        yield from _yield_once(getattr(exc, attr, None))

    original_exception = getattr(exc, "original_exception", None)
    if isinstance(original_exception, BaseException) and original_exception is not exc:
        for payload in _iter_payload_candidates(original_exception):
            yield from _yield_once(payload)

    for arg in getattr(exc, "args", ()) or ():
        yield from _yield_once(arg)

    yield from _yield_once(str(exc))


def _extract_payload_details(payload: Any) -> ProviderErrorDetails:
    if payload is None:
        return ProviderErrorDetails(None, None, None)

    if isinstance(payload, ProviderErrorDetails):
        return payload

    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8", errors="ignore")

    if isinstance(payload, str):
        parsed = _parse_json_like_fragment(payload)
        if parsed is not None:
            parsed_details = _extract_payload_details(parsed)
            if (
                parsed_details.message
                or parsed_details.status_code is not None
                or parsed_details.provider_code is not None
            ):
                return parsed_details

        cleaned = _sanitize_text(_strip_wrapper_prefixes(_normalize_whitespace(payload)))
        if not cleaned:
            return ProviderErrorDetails(None, None, None)
        if re.fullmatch(r"[A-Za-z_][\w.]*?(?:Error|Exception)", cleaned):
            return ProviderErrorDetails(
                None,
                None,
                _extract_provider_code_from_text(cleaned),
            )
        return ProviderErrorDetails(cleaned, None, _extract_provider_code_from_text(cleaned))

    if isinstance(payload, dict):
        status_code = _coerce_int(payload.get("status_code"))
        if status_code is None:
            status_code = _coerce_int(payload.get("code"))
        provider_code = _coerce_code(payload.get("status")) or _coerce_code(
            payload.get("type")
        )

        nested_error = payload.get("error")
        if nested_error is not None:
            nested = _extract_payload_details(nested_error)
            return ProviderErrorDetails(
                nested.message,
                nested.status_code if nested.status_code is not None else status_code,
                nested.provider_code or provider_code,
            )

        for key in (
            "message",
            "detail",
            "error_message",
            "error_description",
            "title",
        ):
            value = payload.get(key)
            if isinstance(value, str):
                return ProviderErrorDetails(value, status_code, provider_code)

        for value in payload.values():
            nested = _extract_payload_details(value)
            if (
                nested.message
                or nested.status_code is not None
                or nested.provider_code is not None
            ):
                return ProviderErrorDetails(
                    nested.message,
                    nested.status_code if nested.status_code is not None else status_code,
                    nested.provider_code or provider_code,
                )

        return ProviderErrorDetails(None, status_code, provider_code)

    if isinstance(payload, (list, tuple)):
        for value in payload:
            nested = _extract_payload_details(value)
            if (
                nested.message
                or nested.status_code is not None
                or nested.provider_code is not None
            ):
                return nested
        return ProviderErrorDetails(None, None, None)

    if isinstance(payload, int):
        return ProviderErrorDetails(None, payload if 100 <= payload <= 599 else None, None)

    return ProviderErrorDetails(None, None, None)


def _parse_json_like_fragment(text: str) -> Any:
    for candidate in _candidate_fragments(text):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(candidate)
            except Exception:
                continue
            if isinstance(parsed, (dict, list)):
                return parsed
    return None


def _candidate_fragments(text: str) -> list[str]:
    stripped = text.strip()
    candidates = [stripped]

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start >= 0 and end > start:
            candidates.append(stripped[start : end + 1])

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _normalize_provider_message(message: Optional[str]) -> Optional[str]:
    if not message:
        return None

    cleaned = _sanitize_text(_strip_wrapper_prefixes(_normalize_whitespace(message)))
    if not cleaned:
        return None

    lowered = cleaned.lower()
    if (
        "prepayment credits are depleted" in lowered
        or "no available credits" in lowered
    ):
        return (
            "Google AI Studio prepay credits are depleted for this billing account. "
            "This is a billing error, not an RPM quota error. Add credits or enable "
            "auto-reload in AI Studio Billing."
        )

    if len(cleaned) > _MAX_MESSAGE_CHARS:
        cleaned = cleaned[: _MAX_MESSAGE_CHARS - 3].rstrip(" .,;:") + "..."
    return cleaned


def _strip_wrapper_prefixes(text: str) -> str:
    previous = None
    cleaned = text.strip()
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = _WRAPPER_PREFIX_RE.sub("", cleaned).strip()
    return cleaned


def _sanitize_text(text: str) -> str:
    cleaned = text
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned.strip()


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_provider_code_from_text(text: str) -> Optional[str]:
    match = re.search(r"\b([A-Z][A-Z0-9_]{2,})\b", text)
    if match:
        return match.group(1)
    return None


def _coerce_code(value: Any) -> Optional[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

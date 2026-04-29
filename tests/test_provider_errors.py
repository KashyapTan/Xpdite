"""Tests for source/llm/core/provider_errors.py."""

from source.llm.core.provider_errors import (
    build_provider_error_message,
    extract_provider_error_details,
)


class DummyProviderError(Exception):
    """Minimal provider-style exception for testing safe error extraction."""

    def __init__(self, message: str, **attrs):
        super().__init__(message)
        for key, value in attrs.items():
            setattr(self, key, value)


def test_extracts_gemini_prepay_depletion_from_wrapped_error():
    exc = DummyProviderError(
        "litellm.RateLimitError: Vertex_ai_betaException - "
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
        "'Your prepayment credits are depleted. Please go to AI Studio at "
        "https://ai.studio/projects to manage your project and billing.', "
        "'status': 'RESOURCE_EXHAUSTED'}}",
        status_code=429,
    )

    assert build_provider_error_message("gemini", exc) == (
        "Gemini API request failed: Google AI Studio prepay credits are depleted "
        "for this billing account. This is a billing error, not an RPM quota "
        "error. Add credits or enable auto-reload in AI Studio Billing."
    )


def test_prefers_structured_body_message_for_openai_style_quota_errors():
    exc = DummyProviderError(
        "RateLimitError",
        status_code=429,
        body={
            "error": {
                "message": "You exceeded your current quota, please check your plan and billing details.",
                "type": "insufficient_quota",
                "code": "insufficient_quota",
            }
        },
    )

    assert build_provider_error_message("openai", exc) == (
        "OpenAI API request failed: You exceeded your current quota, please check "
        "your plan and billing details."
    )


def test_redacts_api_keys_from_extracted_messages():
    exc = DummyProviderError(
        "Bad request for https://example.com/v1?key=AIzaSySuperSecretValue1234567890 "
        "with Authorization: Bearer sk-123456789012345678901234567890",
    )

    message = build_provider_error_message("gemini", exc)

    assert "AIzaSySuperSecretValue1234567890" not in message
    assert "sk-123456789012345678901234567890" not in message
    assert "[REDACTED]" in message


def test_falls_back_to_status_code_when_no_message_exists():
    exc = DummyProviderError("RateLimitError", status_code=429)

    details = extract_provider_error_details(exc)

    assert details.message is None
    assert details.status_code == 429
    assert build_provider_error_message("anthropic", exc) == (
        "Anthropic API request failed: rate limit, quota, or billing capacity "
        "was exhausted."
    )

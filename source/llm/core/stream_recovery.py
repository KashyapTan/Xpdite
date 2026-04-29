"""Shared LiteLLM stream recovery helpers."""

MID_STREAM_RETRY_LIMIT = 1


def get_mid_stream_generated_suffix(
    streamed_text: str,
    generated_content: str,
) -> str:
    """Return the suffix of generated content that has not already been streamed."""
    if not generated_content:
        return ""
    if not streamed_text:
        return generated_content
    if generated_content == streamed_text:
        return ""
    if generated_content.startswith(streamed_text):
        return generated_content[len(streamed_text) :]

    max_overlap = min(len(streamed_text), len(generated_content))
    for overlap in range(max_overlap, 0, -1):
        if streamed_text.endswith(generated_content[:overlap]):
            return generated_content[overlap:]

    if streamed_text in generated_content:
        streamed_idx = generated_content.find(streamed_text)
        if streamed_idx >= 0:
            return generated_content[streamed_idx + len(streamed_text) :]

    return generated_content

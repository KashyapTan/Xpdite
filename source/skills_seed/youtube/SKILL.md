---
name: youtube
description: Guidance for understanding YouTube videos with the watch_youtube_video tool.
trigger-servers: []
---

# YouTube Video Skill

When the user shares, pastes, or references a YouTube URL, immediately call the `watch_youtube_video` tool.
Do not wait for explicit permission to "watch" first.

## Workflow
- Call `watch_youtube_video` with the provided URL.
- If the user asks for timing details, set `include_timestamps=true`.
- Use the returned transcript to answer questions, summarize, quote sections, compare claims, or extract action items.

## Response style
- Before diving into analysis, proactively tell the user what you found:
  - video title
  - channel
  - duration
- Then answer using evidence from the transcript.

## If fallback transcription is denied
- Clearly explain that captions were unavailable and fallback transcription was declined.
- Suggest trying another YouTube video with captions or re-running with approval.


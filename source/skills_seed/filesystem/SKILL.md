---
name: filesystem
description: Guidance for safe file reading, writing, and directory navigation.
trigger-servers: filesystem
---

# File System Skill

## Workflow
- List directory contents before reading or writing to understand the existing structure.
- Always read a file fully before making edits — partial context leads to errors.
- NEVER write to a file without reading it.
- When writing, preserve the original file encoding and line endings.
- Use move/rename rather than write+delete for file restructuring.

## Safety
- Never overwrite files without confirming intent if the content looks user-generated.
- Avoid writing to system directories or paths outside the project root unless explicitly instructed.

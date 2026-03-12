---
name: filesystem
description: Guidance for safe file reading, writing, search, and directory navigation.
trigger-servers: filesystem
---

# File System Skill

## Workflow
- List directory contents before reading or writing to understand the existing structure.
- Always read a file fully before making edits — partial context leads to errors.
- NEVER write to a file without reading it.
- When writing, preserve the original file encoding and line endings.
- Use move/rename rather than write+delete for file restructuring.

## File Search
- Use `glob_files` for file and directory discovery by pattern.
- Use `grep_files` for searching inside file contents.
- `glob_files` and `grep_files` are the required tools for file discovery and file-content search when they can handle the task.
- Do NOT use `run_command` for `grep`, `rg`, `ag`, `find`, `ls`, `dir`, or shell glob expansion when the filesystem tools can do the job.

| Task | Tool | Suggested inputs |
|---|---|---|
| Find files by name or extension | `glob_files` | `pattern="**/*.py"` and optionally `base_path="source"` |
| Search text inside code or docs | `grep_files` | `pattern="RequestContext"`, `file_glob="**/*.py"`, optionally `path="source"` |
| Run a regex search | `grep_files` | `pattern="class\\s+\\w+"`, `is_regex=true`, `file_glob="**/*.py"` |
| Inspect one directory | `list_directory` | `path="..."` |
| Open a specific file | `read_file` | `path="..."` |

- When `truncated: true`, narrow the query instead of retrying broadly:
  - Reduce `base_path` or `path` to a smaller subtree.
  - Add or tighten `file_glob`.
  - Make the search pattern more specific.
  - Leave `include_hidden` off unless hidden files are required.

## Safety
- Never overwrite files without confirming intent if the content looks user-generated.
- Avoid writing to system directories or paths outside the project root unless explicitly instructed.

from mcp_servers.servers.description_format import build_tool_description


MEMLIST_DESCRIPTION = build_tool_description(
    purpose="Browse filesystem-backed long-term memory files and decide what is worth opening in full.",
    use_when="You need prior user preferences, project context, reusable solutions, or session history before answering. Call this near the start of relevant coding, debugging, project, or preference-heavy conversations.",
    inputs="Optional folder (for example 'procedural', 'projects/xpdite', or 'semantic'). Omit it to recursively list the full memory tree.",
    returns="A grouped text listing of matching memory files. Each line includes the exact relative file path to use with memread plus its abstract.",
    notes="Only abstracts are returned here. Use memread on specific paths when an abstract looks relevant. New folders created by memcommit will appear automatically in future memlist calls.",
)

MEMREAD_DESCRIPTION = build_tool_description(
    purpose="Read one memory file in full, including its front matter metadata and markdown body.",
    use_when="memlist surfaced a file whose abstract appears relevant and you need the full details before answering or updating the memory.",
    inputs="path (required relative markdown path exactly as returned by memlist, for example 'procedural/sqlite_deadlock_fix.md').",
    returns="The full raw markdown file text, including front matter and body.",
    notes="Use this before overwriting an existing memory when you need to merge or preserve prior context.",
)

MEMCOMMIT_DESCRIPTION = build_tool_description(
    purpose="Create or overwrite a long-term memory file on disk.",
    use_when="You have learned something worth preserving, such as a stable user preference, a reusable fix, a project-specific note, or a meaningful session summary.",
    inputs="path, title, category, importance (0.0-1.0), tags (string array), abstract (single sentence), and body (markdown).",
    returns="A concise confirmation describing the saved path and whether it was created or updated.",
    notes="Paths must stay inside the memory root and end in .md. Intermediate folders are created automatically. Be selective: low-value or duplicate memories reduce retrieval quality.",
)

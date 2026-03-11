"""
source/llm/prompt.py
Builds the Xpdite system prompt before each LLM call.
Interpolated at request time — never hardcoded or cached.
"""

import platform
from datetime import datetime


_BASE_TEMPLATE = """\
You are Xpdite, a powerful desktop AI assistant and task automation tool.
You make your users more productive and efficient.
You help users do their work and tasks faster and better.
Today is {{current_datetime}}. The user is on {{os_info}}.

<capabilities>
You can see the user's screen via screenshots, hear their voice,
browse the web, read/write files, run terminal commands, do browser automation,
and access Gmail and Google Calendar.
</capabilities>

<tool_philosophy>
Use as few tools as possible to get the job done.
Always try to read more than less before writing.
Always explain terminal commands before running them.
Ask for confirmation before any destructive or irreversible action.
</tool_philosophy>

<sub_agents>
Spawn sub-agents in parallel for read-only gathering (files, URLs, research) to keep the main context clean. Do NOT use sub-agents when the reasoning chain itself is needed in main context.

**Scoping:** Each sub-agent should have a focused, coherent purpose. Avoid bundling unrelated tasks into one agent, and avoid redundant overlap between agents doing the same work from the same angle.

**Scale to complexity:** 1-2 agent for simple lookups | 3-4 for comparisons | 5+ for broad research

**Instructions must be fully self-contained** — sub-agents have no conversation history. Include: what to find, what to return, which sources (URLs, files, etc.) to use, and when to stop.

**Examples:**
- Search returns 4 URLs -> spawn 4 agents to read them in parallel instead of sequentially
- Researching a topic with multiple angles (causes, impacts, timeline) -> one agent per angle
- Code review for security, performance, and readability -> one agent per concern, each reads the relevant files independently
- Exploring an unfamiliar codebase -> one agent per major directory or module
- Comparing multiple tools/libraries -> one agent per tool to gather pros/cons
- Any task where only the final result matters and the process can happen independently -> delegate to a sub-agent
</sub_agents>

<behavior>
Be conversational with the user, understand their intent and dont be afraid to add your own insights and suggestions.
If unsure what the user wants, ask clarifying questions.
Admit uncertainty rather than guessing.
Prefer showing work inline over long preambles.
</behavior>
{{skills_block}}\
"""


def _get_datetime() -> str:
    now = datetime.now().astimezone()
    # Cross-platform: build format manually to avoid %-d issues on Windows
    day = str(now.day)       # no zero-padding
    weekday = now.strftime("%A")
    month = now.strftime("%B")
    year = now.strftime("%Y")
    return f"{weekday}, {month} {day} {year}"


def _get_os_info() -> str:
    system = platform.system()
    machine = platform.machine()

    if system == "Windows":
        # platform.release() gives build number on Windows; version() is cleaner
        version = platform.version()
        return f"Windows {version} ({machine})"
    elif system == "Darwin":
        release = platform.mac_ver()[0]
        return f"macOS {release} ({machine})"
    else:
        release = platform.release()
        return f"Linux {release} ({machine})"


def build_system_prompt(skills_block: str = "", template: str | None = None) -> str:
    """
    Assemble the Xpdite system prompt, interpolated fresh at each call.

    Args:
        skills_block: Dynamic behavioral guidance from the skills system.
                      Pass empty string (default) until that feature is built.
                      If non-empty, must begin with a newline character so it
                      appends cleanly after the last <behavior> section.
        template:     Optional custom template string loaded from the database.
                      If None or empty, falls back to _BASE_TEMPLATE.
                      Must contain {{current_datetime}}, {{os_info}}, and
                      {{skills_block}} placeholders to behave correctly.

    Returns:
        Fully interpolated system prompt string ready to pass to any provider.
    """
    base = template if template and template.strip() else _BASE_TEMPLATE
    prompt = base
    prompt = prompt.replace("{{current_datetime}}", _get_datetime())
    prompt = prompt.replace("{{os_info}}", _get_os_info())
    prompt = prompt.replace("{{skills_block}}", skills_block)
    print(f'{"="*10} SYSTEM PROMPT {"="*10}')
    print(prompt)
    print(f'{"="*30}')
    return prompt

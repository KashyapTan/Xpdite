"""Shell command analysis helpers for the terminal tool.

This module ports a pragmatic subset of the behavior from Claude Code's
shell/search tools into Python:

- explicit shell selection for a combined terminal tool
- better approval-signature normalization
- shell-specific hard blocks for high-risk / obfuscated commands
- destructive warnings for approval UX
- command-specific exit-code semantics
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess


_IS_WINDOWS = platform.system() == "Windows"

_SUPPORTED_SHELLS = frozenset({"auto", "cmd", "powershell", "bash", "sh"})
_WINDOWS_POWERSHELL_NAMES = ("pwsh", "powershell")

_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_BINARY_HIJACK_ENV_RE = re.compile(r"^(?:PATH|LD_[A-Z0-9_]+|DYLD_[A-Z0-9_]+)=", re.I)

_POSIX_TWO_WORD_PREFIXES = frozenset(
    {
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "pip",
        "pip3",
        "git",
        "docker",
        "cargo",
        "uv",
        "bun",
        "pytest",
        "terraform",
        "kubectl",
        "gh",
    }
)

_POWERSHELL_TWO_WORD_PREFIXES = frozenset(
    {
        "git",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "pip",
        "pip3",
        "docker",
        "cargo",
        "uv",
        "bun",
        "gh",
    }
)

_POWERSHELL_ALIASES = {
    "ls": "get-childitem",
    "dir": "get-childitem",
    "cat": "get-content",
    "gc": "get-content",
    "rm": "remove-item",
    "del": "remove-item",
    "rd": "remove-item",
    "rmdir": "remove-item",
    "cd": "set-location",
    "pwd": "get-location",
    "echo": "write-output",
    "sleep": "start-sleep",
    "iwr": "invoke-webrequest",
    "irm": "invoke-restmethod",
    "iex": "invoke-expression",
    "ii": "invoke-item",
    "saps": "start-process",
    "where": "where-object",
}


@dataclass(frozen=True)
class ResolvedShell:
    """Concrete shell process selection."""

    requested: str
    name: str
    executable: str
    argv_prefix: tuple[str, ...]
    display_name: str


@dataclass(frozen=True)
class CommandAnalysis:
    """Terminal-command analysis result."""

    shell: ResolvedShell
    approval_signature: str
    hard_block_reason: str | None = None
    destructive_warning: str | None = None


@dataclass(frozen=True)
class CommandResultSemantics:
    """Interpretation of a process exit code."""

    is_error: bool
    message: str | None = None


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _basename(command_name: str) -> str:
    value = _strip_wrapping_quotes(command_name)
    last_sep = max(value.rfind("/"), value.rfind("\\"))
    if last_sep >= 0:
        value = value[last_sep + 1 :]
    return value


def _resolve_powershell_executable() -> str | None:
    for candidate in _WINDOWS_POWERSHELL_NAMES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    if _IS_WINDOWS:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        classic = os.path.join(
            system_root,
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        if os.path.exists(classic):
            return classic
    return None


def normalize_shell(shell: str | None) -> str:
    value = (shell or "auto").strip().lower()
    if value not in _SUPPORTED_SHELLS:
        raise ValueError(
            f"Unsupported shell '{shell}'. Supported values: auto, cmd, powershell, bash, sh."
        )
    return value


def resolve_shell(shell: str | None) -> ResolvedShell:
    """Resolve a shell selection into an executable + argv prefix."""

    requested = normalize_shell(shell)

    if requested == "auto":
        if _IS_WINDOWS:
            executable = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
            return ResolvedShell(
                requested="auto",
                name="cmd",
                executable=executable,
                argv_prefix=(executable, "/d", "/s", "/c"),
                display_name=Path(executable).name,
            )

        shell_path = os.environ.get("SHELL") or shutil.which("bash") or shutil.which("sh") or "/bin/sh"
        executable = shell_path
        shell_name = Path(shell_path).name.lower()
        use_login = shell_name in {"bash", "zsh", "ksh"}
        return ResolvedShell(
            requested="auto",
            name="bash" if shell_name == "bash" else "sh",
            executable=executable,
            argv_prefix=(executable, "-lc" if use_login else "-c"),
            display_name=Path(executable).name,
        )

    if requested == "cmd":
        if not _IS_WINDOWS:
            raise ValueError("shell='cmd' is only available on Windows.")
        executable = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
        return ResolvedShell(
            requested=requested,
            name="cmd",
            executable=executable,
            argv_prefix=(executable, "/d", "/s", "/c"),
            display_name=Path(executable).name,
        )

    if requested == "powershell":
        executable = _resolve_powershell_executable()
        if not executable:
            raise ValueError(
                "shell='powershell' was requested, but neither pwsh nor powershell was found on PATH."
            )
        exe_name = Path(executable).name.lower()
        if exe_name.startswith("powershell"):
            argv_prefix = (
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
            )
        else:
            argv_prefix = (
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
            )
        return ResolvedShell(
            requested=requested,
            name="powershell",
            executable=executable,
            argv_prefix=argv_prefix,
            display_name=Path(executable).name,
        )

    executable = shutil.which(requested)
    if not executable:
        raise ValueError(f"shell='{requested}' was requested, but '{requested}' was not found on PATH.")

    return ResolvedShell(
        requested=requested,
        name=requested,
        executable=executable,
        argv_prefix=(executable, "-lc" if requested == "bash" else "-c"),
        display_name=Path(executable).name,
    )


def build_subprocess_argv(shell: ResolvedShell, command: str) -> list[str]:
    """Build argv for asyncio.create_subprocess_exec."""

    return [*shell.argv_prefix, command]


def build_pty_command(shell: ResolvedShell, command: str) -> str:
    """Build a PTY spawn command line for pywinpty / shell PTYs."""

    argv = build_subprocess_argv(shell, command)
    return subprocess.list2cmdline(argv) if _IS_WINDOWS else shlex.join(argv)


def _split_tokens(command: str, *, powershell: bool) -> list[str]:
    if powershell:
        token_pattern = r'"[^"]*"|\'[^\']*\'|\S+'
        return re.findall(token_pattern, command)
    try:
        return shlex.split(command, posix=not _IS_WINDOWS)
    except ValueError:
        return command.strip().split()


def _skip_posix_wrappers(tokens: list[str]) -> list[str]:
    index = 0

    while index < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[index]):
        index += 1

    if index < len(tokens) and tokens[index] == "env":
        index += 1
        while index < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[index]):
            index += 1

    if index < len(tokens) and tokens[index] in {"timeout", "gtimeout"}:
        index += 1
        while index < len(tokens) and tokens[index].startswith("-"):
            if tokens[index] in {"-k", "--kill-after", "-s", "--signal"} and index + 1 < len(tokens):
                index += 2
                continue
            index += 1
        if index < len(tokens):
            index += 1

    if index < len(tokens) and tokens[index] == "stdbuf":
        index += 1
        while index < len(tokens) and tokens[index].startswith("-") and index + 1 < len(tokens):
            index += 2

    if index < len(tokens) and tokens[index] == "nohup":
        index += 1

    return tokens[index:]


def _extract_shell_signature(command: str, shell_name: str) -> str:
    trimmed = command.strip()
    if not trimmed:
        return command

    first_statement = re.split(r"(?:&&|\|\||[;&\r\n])", trimmed, maxsplit=1)[0].strip()
    if not first_statement:
        return trimmed

    if shell_name == "powershell":
        tokens = _split_tokens(first_statement, powershell=True)
        if not tokens:
            return first_statement.lower()

        if tokens[0] in {"&", "."} and len(tokens) > 1:
            tokens = tokens[1:]

        command_name = _basename(tokens[0]).lower().removesuffix(".exe")
        command_name = _POWERSHELL_ALIASES.get(command_name, command_name)

        if command_name in {"powershell", "pwsh"} and len(tokens) >= 3 and tokens[1].lower() in {"-command", "-c"}:
            return _extract_shell_signature(tokens[2], "powershell")

        if command_name in _POWERSHELL_TWO_WORD_PREFIXES and len(tokens) > 1:
            return f"{command_name} {_strip_wrapping_quotes(tokens[1]).lower()}"

        if command_name in {"python", "python3", "py"} and len(tokens) > 2 and tokens[1] == "-m":
            return f"{command_name} -m {_strip_wrapping_quotes(tokens[2]).lower()}"

        return command_name

    tokens = _split_tokens(first_statement, powershell=False)
    if not tokens:
        return first_statement.lower()

    tokens = _skip_posix_wrappers(tokens)
    if not tokens:
        return first_statement.lower()

    command_name = _basename(tokens[0]).lower()

    if command_name in {"bash", "sh"} and len(tokens) >= 3 and tokens[1] in {"-c", "-lc"}:
        return _extract_shell_signature(tokens[2], "bash")

    if command_name in _POSIX_TWO_WORD_PREFIXES and len(tokens) > 1:
        return f"{command_name} {_strip_wrapping_quotes(tokens[1]).lower()}"

    if command_name in {"python", "python3", "py"} and len(tokens) > 2 and tokens[1] == "-m":
        return f"{command_name} -m {_strip_wrapping_quotes(tokens[2]).lower()}"

    return command_name


_POSIX_HARD_BLOCKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(^|[;&|]\s*)eval\b", re.I),
        "Command uses eval, which obscures the real command being executed.",
    ),
    (
        re.compile(r"\b(?:curl|wget)\b[^|\r\n;]*\|\s*(?:bash|sh|zsh)\b", re.I),
        "Command downloads remote content and pipes it directly into a shell.",
    ),
    (
        re.compile(r"(^|\s)(?:PATH|LD_[A-Z0-9_]+|DYLD_[A-Z0-9_]+)=", re.I),
        "Command overrides executable search-path variables, which can hijack which binaries run.",
    ),
)

_POWERSHELL_HARD_BLOCKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(^|[;\r\n]\s*)(?:invoke-expression|iex)\b", re.I),
        "Command uses Invoke-Expression/iex, which evaluates arbitrary strings as code.",
    ),
    (
        re.compile(r"\s-(?:encodedcommand|enc|e)\b", re.I),
        "Command uses an encoded PowerShell payload, which obscures intent.",
    ),
    (
        re.compile(r"\b(?:start-process|saps|start)\b[^;\r\n]*\s-(?:verb|v)\s*:?\s*['\"` ]*runas\b", re.I),
        "Command requests elevated privileges via Start-Process -Verb RunAs.",
    ),
    (
        re.compile(r"\badd-type\b", re.I),
        "Command compiles or loads .NET code at runtime via Add-Type.",
    ),
    (
        re.compile(r"\bnew-object\b[^;\r\n]*\s-(?:comobject|com)\b", re.I),
        "Command instantiates a COM object, which can expose execution primitives.",
    ),
    (
        re.compile(r"\b(?:invoke-item|ii)\b", re.I),
        "Invoke-Item opens targets with the default handler and may execute code.",
    ),
    (
        re.compile(r"\bstart-bitstransfer\b|\bbitsadmin(?:\.exe)?\b[^;\r\n]*/transfer\b|\bcertutil(?:\.exe)?\b[^;\r\n]*[-/]urlcache\b", re.I),
        "Command uses a download primitive that can fetch remote payloads.",
    ),
    (
        re.compile(r"\bregister-scheduledtask\b|\bnew-scheduledtask\b|\bset-scheduledtask\b|\bschtasks(?:\.exe)?\b[^;\r\n]*/(?:create|change)\b", re.I),
        "Command creates or changes a scheduled task, which is a persistence primitive.",
    ),
    (
        re.compile(r"(^|\s)\$env:PATH\s*=", re.I),
        "Command modifies $env:PATH, which can hijack which binaries run.",
    ),
)

_POSIX_DESTRUCTIVE_WARNINGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.I), "Note: may discard uncommitted changes."),
    (re.compile(r"\bgit\s+push\b[^;&|\r\n]*\s+(?:--force|--force-with-lease|-f)\b", re.I), "Note: may overwrite remote history."),
    (re.compile(r"\bgit\s+clean\b(?![^;&|\r\n]*(?:-[A-Za-z]*n|--dry-run))[^;&|\r\n]*-[A-Za-z]*f", re.I), "Note: may permanently delete untracked files."),
    (re.compile(r"\bgit\s+(?:checkout|restore)\s+(?:--\s+)?\.[ \t]*($|[;&|\r\n])", re.I), "Note: may discard all working tree changes."),
    (re.compile(r"\bgit\s+stash\s+(?:drop|clear)\b", re.I), "Note: may permanently remove stashed changes."),
    (re.compile(r"\bgit\s+branch\s+(?:-D|--delete\s+--force|--force\s+--delete)\b", re.I), "Note: may force-delete a branch."),
    (re.compile(r"\bgit\s+(?:commit|push|merge)\b[^;&|\r\n]*--no-verify\b", re.I), "Note: may skip safety hooks."),
    (re.compile(r"\bgit\s+commit\b[^;&|\r\n]*--amend\b", re.I), "Note: may rewrite the last commit."),
    (re.compile(r"(^|[;&|\r\n]\s*)rm\s+-[A-Za-z]*[rR][A-Za-z]*f|(^|[;&|\r\n]\s*)rm\s+-[A-Za-z]*f[A-Za-z]*[rR]", re.I), "Note: may recursively force-remove files."),
    (re.compile(r"(^|[;&|\r\n]\s*)rm\s+-[A-Za-z]*[rR]", re.I), "Note: may recursively remove files."),
    (re.compile(r"(^|[;&|\r\n]\s*)rm\s+-[A-Za-z]*f", re.I), "Note: may force-remove files."),
    (re.compile(r"\b(?:DROP|TRUNCATE)\s+(?:TABLE|DATABASE|SCHEMA)\b", re.I), "Note: may drop or truncate database objects."),
    (re.compile(r"\bDELETE\s+FROM\s+\w+[ \t]*(?:;|\"|'|\r?\n|$)", re.I), "Note: may delete all rows from a database table."),
    (re.compile(r"\bkubectl\s+delete\b", re.I), "Note: may delete Kubernetes resources."),
    (re.compile(r"\bterraform\s+destroy\b", re.I), "Note: may destroy Terraform infrastructure."),
    (re.compile(r"\brd\s+/s\s+/q\b|\brmdir\s+/s\s+/q\b|\bdel\s+/[fFsS]+\b", re.I), "Note: may force-delete files or directories."),
)

_POWERSHELL_DESTRUCTIVE_WARNINGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:^|[|;&\r\n({])\s*(?:Remove-Item|rm|del|rd|rmdir|ri)\b[^|;&\r\n}]*-Recurse\b[^|;&\r\n}]*-Force\b", re.I), "Note: may recursively force-remove files."),
    (re.compile(r"(?:^|[|;&\r\n({])\s*(?:Remove-Item|rm|del|rd|rmdir|ri)\b[^|;&\r\n}]*-Recurse\b", re.I), "Note: may recursively remove files."),
    (re.compile(r"(?:^|[|;&\r\n({])\s*(?:Remove-Item|rm|del|rd|rmdir|ri)\b[^|;&\r\n}]*-Force\b", re.I), "Note: may force-remove files."),
    (re.compile(r"\bClear-Content\b[^|;&\r\n]*\*", re.I), "Note: may clear content of multiple files."),
    (re.compile(r"\bFormat-Volume\b|\bClear-Disk\b", re.I), "Note: may destroy storage data."),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.I), "Note: may discard uncommitted changes."),
    (re.compile(r"\bgit\s+push\b[^|;&\r\n]*\s+(?:--force|--force-with-lease|-f)\b", re.I), "Note: may overwrite remote history."),
    (re.compile(r"\bgit\s+clean\b(?![^|;&\r\n]*(?:-[A-Za-z]*n|--dry-run))[^|;&\r\n]*-[A-Za-z]*f", re.I), "Note: may permanently delete untracked files."),
    (re.compile(r"\bgit\s+stash\s+(?:drop|clear)\b", re.I), "Note: may permanently remove stashed changes."),
    (re.compile(r"\b(?:DROP|TRUNCATE)\s+(?:TABLE|DATABASE|SCHEMA)\b", re.I), "Note: may drop or truncate database objects."),
    (re.compile(r"\bStop-Computer\b|\bRestart-Computer\b", re.I), "Note: will shut down or restart the machine."),
    (re.compile(r"\bClear-RecycleBin\b", re.I), "Note: permanently deletes recycled files."),
)


def _find_first_match_warning(
    command: str,
    patterns: tuple[tuple[re.Pattern[str], str], ...],
) -> str | None:
    for pattern, warning in patterns:
        if pattern.search(command):
            return warning
    return None


def analyze_command(command: str, shell: str | None) -> CommandAnalysis:
    """Analyze a terminal command before approval/execution."""

    resolved_shell = resolve_shell(shell)
    shell_name = resolved_shell.name
    signature = _extract_shell_signature(command, "powershell" if shell_name == "powershell" else "bash")

    if shell_name == "powershell":
        hard_block = _find_first_match_warning(command, _POWERSHELL_HARD_BLOCKS)
        warning = _find_first_match_warning(command, _POWERSHELL_DESTRUCTIVE_WARNINGS)
    else:
        hard_block = _find_first_match_warning(command, _POSIX_HARD_BLOCKS)
        warning = _find_first_match_warning(command, _POSIX_DESTRUCTIVE_WARNINGS)

    return CommandAnalysis(
        shell=resolved_shell,
        approval_signature=signature,
        hard_block_reason=hard_block,
        destructive_warning=warning,
    )


def interpret_command_result(
    command: str,
    exit_code: int,
    shell_name: str,
) -> CommandResultSemantics:
    """Interpret exit codes for commands that use non-zero informational exits."""

    if shell_name == "powershell":
        base = _extract_shell_signature(command, "powershell")
        if base.startswith("grep") or base.startswith("rg") or base.startswith("findstr"):
            if exit_code == 1:
                return CommandResultSemantics(is_error=False, message="No matches found.")
            return CommandResultSemantics(is_error=exit_code >= 2)
        if base.startswith("robocopy"):
            if exit_code >= 8:
                return CommandResultSemantics(is_error=True)
            if exit_code == 0:
                return CommandResultSemantics(
                    is_error=False, message="No files copied (already in sync)."
                )
            return CommandResultSemantics(
                is_error=False,
                message="Robocopy completed without copy errors.",
            )
        return CommandResultSemantics(
            is_error=exit_code != 0,
            message=f"Command failed with exit code {exit_code}" if exit_code != 0 else None,
        )

    base = _extract_shell_signature(command, "bash")
    if base in {"grep", "rg", "findstr"}:
        if exit_code == 1:
            return CommandResultSemantics(is_error=False, message="No matches found.")
        return CommandResultSemantics(is_error=exit_code >= 2)
    if base == "find":
        if exit_code == 1:
            return CommandResultSemantics(
                is_error=False,
                message="Some directories were inaccessible.",
            )
        return CommandResultSemantics(is_error=exit_code >= 2)
    if base == "diff":
        if exit_code == 1:
            return CommandResultSemantics(is_error=False, message="Files differ.")
        return CommandResultSemantics(is_error=exit_code >= 2)
    if base in {"test", "["}:
        if exit_code == 1:
            return CommandResultSemantics(is_error=False, message="Condition is false.")
        return CommandResultSemantics(is_error=exit_code >= 2)
    return CommandResultSemantics(
        is_error=exit_code != 0,
        message=f"Command failed with exit code {exit_code}" if exit_code != 0 else None,
    )

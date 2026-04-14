"""Host-side runtime for Claude-compatible plugin hooks."""

from __future__ import annotations

import asyncio
import copy
import fnmatch
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import requests

from ...infrastructure.config import (
    MARKETPLACE_HOOK_TRANSCRIPTS_DIR,
    MARKETPLACE_PLUGIN_DATA_DIR,
    PROJECT_ROOT,
)

if TYPE_CHECKING:
    from ..chat.tab_manager import TabState

logger = logging.getLogger(__name__)

_DEFAULT_COMMAND_TIMEOUT_SECONDS = 600.0
_DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
_SUPPORTED_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
}
_BLOCKING_EVENTS = {
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
}
_SUPPORTED_TYPES = {"command", "http"}
_BUILTIN_SUBSTITUTIONS = {
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
    "XPDITE_MARKETPLACE_ROOT",
}
_TOOL_NAME_ALIASES = {
    "run_command": "Bash",
    "read_file": "Read",
    "write_file": "Write",
}
_TOOL_INPUT_FIELD_ALIASES = {
    "path": "file_path",
}
_SUPPORTED_SHELLS = {"bash", "powershell"}
_USER_CONFIG_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PIPE_EXACT_MATCH_RE = re.compile(r"^[A-Za-z0-9_:-]+(?:\|[A-Za-z0-9_:-]+)+$")
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
_SHELL_ENV_RE = re.compile(r"(?<!\\)(?:\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*))")
_PERMISSION_RULE_RE = re.compile(r"^(?P<tool>[A-Za-z0-9_:-]+)(?:\((?P<specifier>.*)\))?$")


@dataclass(frozen=True)
class HookHandler:
    install_id: str
    hook_id: str
    event: str
    matcher: Optional[str]
    condition: Optional[str]
    hook_type: str
    command: Optional[str]
    url: Optional[str]
    shell: Optional[str]
    timeout_seconds: float
    status_message: Optional[str]
    headers: dict[str, str]
    allowed_env_vars: list[str]
    supported: bool
    unsupported_reasons: list[str]
    required_secrets: list[str]
    source: str
    order: int
    raw: dict[str, Any]


@dataclass
class RegisteredHookInstall:
    install_id: str
    install_root: str
    plugin_data_dir: str
    enabled: bool
    normalized_hooks: dict[str, Any]
    handlers_by_event: dict[str, list[HookHandler]]
    supported_event_count: int
    unsupported_event_count: int
    supported_types: list[str]
    unsupported_types: list[str]
    missing_secrets: list[str]
    blocked_reasons: list[str]
    registered_handler_count: int
    compatibility_warnings: list[str]
    last_runtime_error: Optional[str] = None


@dataclass
class HookDispatchResult:
    blocked: bool = False
    reason: Optional[str] = None
    continue_processing: bool = True
    system_messages: list[str] = field(default_factory=list)
    additional_context: list[str] = field(default_factory=list)
    updated_input: Optional[dict[str, Any]] = None
    updated_mcp_tool_output: Any = None
    permission_decision: Optional[str] = None
    permission_decision_reason: Optional[str] = None
    suppress_output: bool = False
    conflicts: list[str] = field(default_factory=list)
    runtime_messages: list[str] = field(default_factory=list)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    parts = [part for part in normalized.split("/") if part and part != "."]
    if ".." in parts:
        raise ValueError(f"Invalid relative path: {path}")
    return "/".join(parts)


def _safe_within(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    resolved_root = root.resolve()
    if not str(target).startswith(str(resolved_root)):
        raise ValueError(f"Unsafe hook path outside plugin root: {relative}")
    return target


def _unique_str_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _looks_like_regex(pattern: str) -> bool:
    return bool(re.search(r"[\\\[\]\(\)\{\}\^\$\+\?\*]", pattern))


def _matcher_matches(matcher: Optional[str], value: str) -> bool:
    if not matcher:
        return True
    normalized = matcher.strip()
    if not normalized:
        return True
    if _PIPE_EXACT_MATCH_RE.fullmatch(normalized):
        return value in normalized.split("|")
    if _looks_like_regex(normalized):
        try:
            return re.search(normalized, value) is not None
        except re.error:
            logger.warning("Invalid hook matcher regex: %s", normalized)
            return False
    return value == normalized


def _collect_string_candidates(value: Any) -> list[str]:
    candidates: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            candidates.extend(_collect_string_candidates(child))
        try:
            candidates.append(_json_dumps(value))
        except Exception:
            pass
    elif isinstance(value, list):
        for child in value:
            candidates.extend(_collect_string_candidates(child))
    elif isinstance(value, (str, int, float, bool)):
        candidates.append(str(value))
    return _unique_str_list(candidates)


def _tool_input_candidates(tool_input: dict[str, Any]) -> list[str]:
    candidates = _collect_string_candidates(tool_input)
    for key in (
        "command",
        "file_path",
        "path",
        "source_path",
        "destination_path",
        "cwd",
        "new_string",
    ):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            candidates.insert(0, value)
    return _unique_str_list(candidates)


def _permission_rule_matches(
    rule: Optional[str],
    tool_names: set[str],
    tool_input: dict[str, Any],
) -> bool:
    if not rule:
        return True
    normalized = rule.strip()
    if not normalized:
        return True
    match = _PERMISSION_RULE_RE.fullmatch(normalized)
    if not match:
        return False
    tool_name = str(match.group("tool") or "").strip()
    if tool_name not in tool_names:
        return False
    specifier = match.group("specifier")
    if specifier is None or not specifier.strip():
        return True
    return any(
        fnmatch.fnmatchcase(candidate, specifier.strip())
        for candidate in _tool_input_candidates(tool_input)
    )


def _collect_placeholders(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            names.extend(_collect_placeholders(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(_collect_placeholders(child))
    elif isinstance(value, str):
        names.extend(match.strip() for match in _PLACEHOLDER_RE.findall(value))
    return _unique_str_list(names)


def _filter_required_secrets(names: list[str]) -> list[str]:
    return [name for name in names if name and name not in _BUILTIN_SUBSTITUTIONS]


def _normalize_user_config_key(name: str) -> Optional[str]:
    normalized = str(name or "").strip()
    if not normalized or not _USER_CONFIG_KEY_RE.fullmatch(normalized):
        return None
    return normalized


def _user_config_env_var(name: str) -> str:
    return f"CLAUDE_PLUGIN_OPTION_{name.upper()}"


def _normalize_required_secret_names(
    names: list[str],
    user_config_keys: set[str],
) -> list[str]:
    normalized_names: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        if not name or name in _BUILTIN_SUBSTITUTIONS:
            continue
        if name.startswith("user_config."):
            user_key = _normalize_user_config_key(name.split(".", 1)[1])
            if user_key and user_key in user_config_keys:
                normalized_names.append(user_key)
                continue
        if name.startswith("CLAUDE_PLUGIN_OPTION_"):
            suffix = name.removeprefix("CLAUDE_PLUGIN_OPTION_").strip()
            for user_key in user_config_keys:
                if suffix == user_key.upper():
                    normalized_names.append(user_key)
                    break
            else:
                normalized_names.append(name)
            continue
        normalized_names.append(name)
    return _unique_str_list(normalized_names)


def _substitute_placeholders(value: str, substitutions: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        return substitutions.get(name, match.group(0))

    return _PLACEHOLDER_RE.sub(_replace, value)


def _interpolate_allowed_env_vars(
    value: str,
    allowed_env_vars: list[str],
    env_map: dict[str, str],
) -> str:
    if not value or not allowed_env_vars:
        return value
    allowed = set(allowed_env_vars)

    def _replace(match: re.Match[str]) -> str:
        name = (match.group(1) or match.group(2) or "").strip()
        if name not in allowed:
            return match.group(0)
        return env_map.get(name, match.group(0))

    return _SHELL_ENV_RE.sub(_replace, value)


def _make_hidden_context_block(messages: list[str]) -> str:
    if not messages:
        return ""
    content = "\n\n".join(message.strip() for message in messages if message.strip())
    if not content:
        return ""
    return "[Claude-compatible hook context]\n" + content


class HooksRuntime:
    """Runtime registry, session management, and execution for plugin hooks."""

    def __init__(self) -> None:
        self._registered_installs: dict[str, RegisteredHookInstall] = {}

    def normalize_plugin_hooks(
        self,
        plugin_manifest: dict[str, Any],
        *,
        install_root: Path,
        install_id: str,
    ) -> dict[str, Any]:
        raw_hooks = plugin_manifest.get("hooks")
        sources: list[tuple[str, dict[str, Any]]] = []
        default_hooks_path = install_root / "hooks" / "hooks.json"

        if raw_hooks is None:
            if default_hooks_path.exists():
                sources.append(
                    (
                        "hooks/hooks.json",
                        self._load_hook_config_from_file(install_root, "hooks/hooks.json"),
                    )
                )
        else:
            for index, entry in enumerate(self._iter_hook_source_entries(raw_hooks), start=1):
                if isinstance(entry, str):
                    relative = _normalize_relative_path(entry)
                    sources.append(
                        (relative, self._load_hook_config_from_file(install_root, relative))
                    )
                    continue
                if isinstance(entry, dict):
                    source_label = "plugin.json"
                    if len(sources) > 0 or isinstance(raw_hooks, list):
                        source_label = f"inline-{index}"
                    sources.append((source_label, entry))

        description = ""
        normalized_events: list[dict[str, Any]] = []
        supported_types: list[str] = []
        unsupported_types: list[str] = []
        supported_events: list[str] = []
        unsupported_events: list[str] = []
        warnings: list[str] = []
        handler_count = 0
        order = 0
        user_config_entries: list[dict[str, Any]] = []
        raw_user_config = (
            plugin_manifest.get("userConfig")
            if isinstance(plugin_manifest.get("userConfig"), dict)
            else {}
        )
        user_config_keys: set[str] = set()
        for key, value in dict(raw_user_config).items():
            normalized_key = _normalize_user_config_key(str(key))
            if not normalized_key:
                warnings.append(
                    f"Plugin userConfig key '{key}' is invalid and was ignored for hook runtime compatibility."
                )
                continue
            entry = value if isinstance(value, dict) else {}
            user_config_entries.append(
                {
                    "key": normalized_key,
                    "description": str(entry.get("description") or "").strip(),
                    "sensitive": bool(entry.get("sensitive")),
                    "env_var": _user_config_env_var(normalized_key),
                }
            )
            user_config_keys.add(normalized_key)

        for source_label, config in sources:
            if not description:
                description = str(config.get("description") or "").strip()
            hooks_config = config.get("hooks") if isinstance(config.get("hooks"), dict) else config
            if not isinstance(hooks_config, dict):
                warnings.append(f"Hook source '{source_label}' did not contain a valid hooks object.")
                continue

            for event_name, groups in hooks_config.items():
                if not isinstance(groups, list):
                    continue
                for group_index, group in enumerate(groups):
                    if isinstance(group, list):
                        group_dict: dict[str, Any] = {"hooks": group}
                    elif isinstance(group, dict):
                        group_dict = copy.deepcopy(group)
                    else:
                        continue
                    matcher = str(group_dict.get("matcher") or "").strip() or None
                    group_condition = str(group_dict.get("if") or "").strip() or None
                    hook_entries = group_dict.get("hooks")
                    if not isinstance(hook_entries, list):
                        continue

                    normalized_hooks: list[dict[str, Any]] = []
                    for hook_index, hook in enumerate(hook_entries):
                        if not isinstance(hook, dict):
                            continue
                        order += 1
                        normalized_hook = self._normalize_hook_handler(
                            install_id=install_id,
                            event_name=event_name,
                            source=source_label,
                            order=order,
                            group_index=group_index,
                            hook_index=hook_index,
                            group_condition=group_condition,
                            raw_hook=hook,
                            user_config_keys=user_config_keys,
                        )
                        handler_count += 1
                        normalized_hooks.append(normalized_hook)
                        hook_type = str(normalized_hook.get("type") or "").strip().lower()
                        if normalized_hook.get("supported"):
                            if hook_type:
                                supported_types.append(hook_type)
                            supported_events.append(event_name)
                        else:
                            if hook_type:
                                unsupported_types.append(hook_type)
                            unsupported_events.append(event_name)

                    if normalized_hooks:
                        normalized_events.append(
                            {
                                "event": event_name,
                                "matcher": matcher,
                                "if": group_condition,
                                "source": source_label,
                                "hooks": normalized_hooks,
                            }
                        )

        unsupported_types_list = sorted(set(unsupported_types) - _SUPPORTED_TYPES)
        if unsupported_types_list:
            warnings.append(
                "Claude hook types preserved but not executed in Xpdite: "
                + ", ".join(unsupported_types_list)
                + "."
            )
        unsupported_events_list = sorted(set(unsupported_events) - _SUPPORTED_EVENTS)
        if unsupported_events_list:
            warnings.append(
                "Claude hook events preserved but not executed in Xpdite: "
                + ", ".join(unsupported_events_list)
                + "."
            )

        required_secrets = _normalize_required_secret_names(
            _collect_placeholders(normalized_events)
            + [
                name
                for event in normalized_events
                for hook in event.get("hooks") or []
                for name in list(hook.get("allowed_env_vars") or [])
            ],
            user_config_keys,
        )

        return {
            "description": description,
            "events": normalized_events,
            "handler_count": handler_count,
            "supported_event_count": len(set(supported_events) & _SUPPORTED_EVENTS),
            "unsupported_event_count": len(set(unsupported_events) - _SUPPORTED_EVENTS),
            "supported_types": sorted(set(supported_types)),
            "unsupported_types": sorted(set(unsupported_types_list)),
            "required_secrets": _unique_str_list(required_secrets),
            "user_config": user_config_entries,
            "compatibility_warnings": _unique_str_list(warnings),
        }

    async def rehydrate_enabled_installs_async(
        self,
        installs: list[dict[str, Any]],
    ) -> None:
        for install in installs:
            if not install.get("enabled"):
                continue
            await self.register_install_async(install)

    async def register_install_async(self, install: dict[str, Any]) -> None:
        hook_manifest = (install.get("component_manifest") or {}).get("hooks")
        install_id = str(install.get("id") or "")
        if not install_id:
            return
        if not install.get("enabled") or not isinstance(hook_manifest, dict):
            self._registered_installs.pop(install_id, None)
            return
        state = self._build_install_state(install)
        if state is None:
            self._registered_installs.pop(install_id, None)
            return
        self._registered_installs[install_id] = state

    async def unregister_install_async(self, install_id: str) -> None:
        self._registered_installs.pop(install_id, None)

    def build_runtime_summary(self, install: dict[str, Any]) -> dict[str, Any]:
        hook_manifest = (install.get("component_manifest") or {}).get("hooks")
        if not isinstance(hook_manifest, dict):
            return {
                "has_hooks": False,
                "registered_handler_count": 0,
                "supported_event_count": 0,
                "unsupported_event_count": 0,
                "supported_types": [],
                "unsupported_types": [],
                "status": "inactive",
                "blocked_reasons": [],
                "missing_secrets": [],
                "last_runtime_error": None,
            }

        install_id = str(install.get("id") or "")
        state = self._registered_installs.get(install_id) or self._build_install_state(install)
        supported_types = list(hook_manifest.get("supported_types") or [])
        unsupported_types = list(hook_manifest.get("unsupported_types") or [])
        supported_event_count = int(hook_manifest.get("supported_event_count") or 0)
        unsupported_event_count = int(hook_manifest.get("unsupported_event_count") or 0)

        registered_handler_count = state.registered_handler_count if state else 0
        missing_secrets = state.missing_secrets if state else []
        blocked_reasons = state.blocked_reasons if state else []
        last_runtime_error = state.last_runtime_error if state else None

        if not install.get("enabled"):
            status = "inactive"
        elif registered_handler_count == 0:
            status = "blocked"
        elif missing_secrets or blocked_reasons or unsupported_event_count or unsupported_types:
            status = "degraded"
        else:
            status = "active"

        return {
            "has_hooks": True,
            "registered_handler_count": registered_handler_count,
            "supported_event_count": supported_event_count,
            "unsupported_event_count": unsupported_event_count,
            "supported_types": supported_types,
            "unsupported_types": unsupported_types,
            "status": status,
            "blocked_reasons": blocked_reasons,
            "missing_secrets": missing_secrets,
            "last_runtime_error": last_runtime_error,
        }

    async def ensure_session_started(
        self,
        tab_state: "TabState",
        *,
        source: str = "startup",
        force_new_session: bool = False,
    ) -> HookDispatchResult:
        session = self._ensure_hook_session(tab_state, force_new_session=force_new_session)
        if session.get("started") and not force_new_session:
            return HookDispatchResult()
        session["started"] = True
        session["start_source"] = source
        payload = self._build_common_payload(tab_state, "SessionStart")
        payload["source"] = source
        return await self._dispatch_event("SessionStart", payload, tab_state=tab_state)

    async def append_transcript_entry(
        self,
        tab_state: "TabState",
        *,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        session = self._ensure_hook_session(tab_state)
        transcript_path = Path(str(session["transcript_path"]))
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }

        def _append() -> None:
            with transcript_path.open("a", encoding="utf-8") as handle:
                handle.write(_json_dumps(payload) + "\n")

        await asyncio.to_thread(_append)

    async def dispatch_user_prompt_submit(
        self,
        tab_state: "TabState",
        *,
        prompt: str,
        llm_prompt: str,
        action: str,
        model: str,
    ) -> HookDispatchResult:
        payload = self._build_common_payload(tab_state, "UserPromptSubmit")
        payload.update(
            {
                "prompt": prompt,
                "llm_prompt": llm_prompt,
                "action": action,
                "model": model,
            }
        )
        return await self._dispatch_event("UserPromptSubmit", payload, tab_state=tab_state)

    async def dispatch_pre_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        server_name: str,
        tab_state: Optional["TabState"] = None,
    ) -> HookDispatchResult:
        resolved_tab_state = tab_state or self._current_tab_state()
        payload = self._build_common_payload(resolved_tab_state, "PreToolUse")
        payload.update(self._build_tool_payload(tool_name, tool_input, server_name=server_name))
        return await self._dispatch_event("PreToolUse", payload, tab_state=resolved_tab_state)

    async def dispatch_post_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_response: Any,
        *,
        server_name: str,
        tab_state: Optional["TabState"] = None,
    ) -> HookDispatchResult:
        resolved_tab_state = tab_state or self._current_tab_state()
        payload = self._build_common_payload(resolved_tab_state, "PostToolUse")
        payload.update(self._build_tool_payload(tool_name, tool_input, server_name=server_name))
        payload["tool_response"] = tool_response
        return await self._dispatch_event("PostToolUse", payload, tab_state=resolved_tab_state)

    async def dispatch_post_tool_use_failure(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        error: str,
        *,
        server_name: str,
        tab_state: Optional["TabState"] = None,
    ) -> HookDispatchResult:
        resolved_tab_state = tab_state or self._current_tab_state()
        payload = self._build_common_payload(resolved_tab_state, "PostToolUseFailure")
        payload.update(self._build_tool_payload(tool_name, tool_input, server_name=server_name))
        payload["tool_error"] = error
        return await self._dispatch_event(
            "PostToolUseFailure",
            payload,
            tab_state=resolved_tab_state,
        )

    async def dispatch_stop(
        self,
        tab_state: "TabState",
        *,
        response_text: str,
        conversation_id: Optional[str],
        tool_calls: list[dict[str, Any]],
        action: str,
        model: str,
    ) -> HookDispatchResult:
        payload = self._build_common_payload(tab_state, "Stop")
        payload.update(
            {
                "response": response_text,
                "conversation_id": conversation_id,
                "tool_calls": tool_calls,
                "action": action,
                "model": model,
            }
        )
        return await self._dispatch_event("Stop", payload, tab_state=tab_state)

    def build_user_prompt_context(self, dispatch_result: HookDispatchResult) -> str:
        return _make_hidden_context_block(
            [*dispatch_result.system_messages, *dispatch_result.additional_context]
        )

    def build_stop_continuation_prompt(
        self,
        dispatch_result: HookDispatchResult,
        *,
        prior_response: str,
    ) -> str:
        context_bits = [*dispatch_result.system_messages, *dispatch_result.additional_context]
        if dispatch_result.reason:
            context_bits.append(dispatch_result.reason)
        context_text = "\n\n".join(bit.strip() for bit in context_bits if bit.strip())
        if not context_text:
            context_text = "Continue and revise the previous answer to satisfy the Claude-compatible Stop hook."
        return (
            "The previous assistant answer was blocked by a Claude-compatible Stop hook.\n\n"
            f"Blocked answer:\n{prior_response}\n\n"
            f"Hook guidance:\n{context_text}\n\n"
            "Continue the answer, revise it if needed, and return the best final response."
        )

    def set_stop_hook_active(self, tab_state: "TabState", active: bool) -> None:
        session = self._ensure_hook_session(tab_state)
        session["stop_hook_active"] = active

    def stop_hook_active(self, tab_state: "TabState") -> bool:
        session = self._ensure_hook_session(tab_state)
        return bool(session.get("stop_hook_active"))

    def _iter_hook_source_entries(self, raw_hooks: Any) -> list[Any]:
        if isinstance(raw_hooks, list):
            return list(raw_hooks)
        return [raw_hooks]

    def _load_hook_config_from_file(
        self,
        install_root: Path,
        relative_path: str,
    ) -> dict[str, Any]:
        target = _safe_within(install_root, relative_path)
        if not target.exists():
            raise ValueError(f"Plugin hook config '{relative_path}' does not exist")
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Plugin hook config '{relative_path}' must be a JSON object")
        return payload

    def _normalize_hook_handler(
        self,
        *,
        install_id: str,
        event_name: str,
        source: str,
        order: int,
        group_index: int,
        hook_index: int,
        group_condition: Optional[str],
        raw_hook: dict[str, Any],
        user_config_keys: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        resolved_user_config_keys = user_config_keys or set()
        hook_type = str(raw_hook.get("type") or "").strip().lower()
        command = str(raw_hook.get("command") or "").strip() or None
        url = str(raw_hook.get("url") or raw_hook.get("endpoint") or "").strip() or None
        shell = str(raw_hook.get("shell") or "").strip().lower() or None
        condition = str(raw_hook.get("if") or group_condition or "").strip() or None
        timeout_raw = raw_hook.get("timeout")
        timeout_seconds = _DEFAULT_COMMAND_TIMEOUT_SECONDS if hook_type == "command" else _DEFAULT_HTTP_TIMEOUT_SECONDS
        if timeout_raw is not None:
            try:
                timeout_seconds = max(0.1, float(timeout_raw))
            except (TypeError, ValueError):
                pass
        headers = raw_hook.get("headers") if isinstance(raw_hook.get("headers"), dict) else {}
        allowed_env_vars = [
            str(name).strip()
            for name in list(raw_hook.get("allowedEnvVars") or [])
            if str(name).strip()
        ]

        unsupported_reasons: list[str] = []
        if event_name not in _SUPPORTED_EVENTS:
            unsupported_reasons.append(f"Unsupported Claude hook event '{event_name}' in Xpdite v1.")
        if hook_type not in _SUPPORTED_TYPES:
            unsupported_reasons.append(f"Unsupported Claude hook type '{hook_type}' in Xpdite v1.")
        if raw_hook.get("async"):
            unsupported_reasons.append("Async Claude hooks are not supported in Xpdite v1.")
        if raw_hook.get("asyncRewake"):
            unsupported_reasons.append("asyncRewake is not supported in Xpdite v1.")
        if shell and shell not in _SUPPORTED_SHELLS:
            unsupported_reasons.append(f"Unsupported hook shell '{shell}'.")
        if hook_type == "command" and not command:
            unsupported_reasons.append("Command hooks must declare a command.")
        if hook_type == "http" and not url:
            unsupported_reasons.append("HTTP hooks must declare a URL.")

        supported = not unsupported_reasons
        required_secrets = _normalize_required_secret_names(
            _collect_placeholders(raw_hook) + allowed_env_vars,
            resolved_user_config_keys,
        )
        return {
            "id": f"{event_name}:{group_index}:{hook_index}:{order}",
            "type": hook_type,
            "command": command,
            "url": url,
            "timeout_seconds": timeout_seconds,
            "shell": shell,
            "status_message": str(raw_hook.get("statusMessage") or "").strip() or None,
            "headers": {
                str(key): str(value)
                for key, value in headers.items()
                if isinstance(key, str)
            },
            "allowed_env_vars": allowed_env_vars,
            "if": condition,
            "supported": supported,
            "unsupported_reasons": unsupported_reasons,
            "required_secrets": required_secrets,
            "source": source,
            "order": order,
            "raw": copy.deepcopy(raw_hook),
            "install_id": install_id,
            "event": event_name,
        }

    def _build_install_state(
        self,
        install: dict[str, Any],
    ) -> Optional[RegisteredHookInstall]:
        component_manifest = install.get("component_manifest") or {}
        normalized_hooks = component_manifest.get("hooks")
        if not isinstance(normalized_hooks, dict):
            return None

        install_id = str(install.get("id") or "")
        install_root = str(install.get("install_root") or "")
        install_root_path = Path(install_root) if install_root else PROJECT_ROOT
        plugin_data_dir = MARKETPLACE_PLUGIN_DATA_DIR / install_id
        plugin_data_dir.mkdir(parents=True, exist_ok=True)

        available_values = self._install_substitutions(install)
        available_secret_names = {
            key
            for key, value in available_values.items()
            if isinstance(value, str) and value != ""
        }
        handlers_by_event: dict[str, list[HookHandler]] = {}
        missing_secrets: list[str] = []
        blocked_reasons: list[str] = []
        registered_handler_count = 0

        for event_group in list(normalized_hooks.get("events") or []):
            event_name = str(event_group.get("event") or "").strip()
            matcher = str(event_group.get("matcher") or "").strip() or None
            group_condition = str(event_group.get("if") or "").strip() or None
            source = str(event_group.get("source") or "plugin.json")
            for hook in list(event_group.get("hooks") or []):
                if not isinstance(hook, dict):
                    continue
                required_secrets = [
                    name
                    for name in list(hook.get("required_secrets") or [])
                    if name not in available_secret_names and name not in os.environ
                ]
                hook_handler = HookHandler(
                    install_id=install_id,
                    hook_id=str(hook.get("id") or uuid.uuid4().hex),
                    event=event_name,
                    matcher=matcher,
                    condition=str(hook.get("if") or group_condition or "").strip() or None,
                    hook_type=str(hook.get("type") or "").strip().lower(),
                    command=str(hook.get("command") or "").strip() or None,
                    url=str(hook.get("url") or "").strip() or None,
                    shell=str(hook.get("shell") or "").strip().lower() or None,
                    timeout_seconds=float(hook.get("timeout_seconds") or _DEFAULT_COMMAND_TIMEOUT_SECONDS),
                    status_message=str(hook.get("status_message") or "").strip() or None,
                    headers={
                        str(key): str(value)
                        for key, value in dict(hook.get("headers") or {}).items()
                    },
                    allowed_env_vars=[
                        str(value).strip()
                        for value in list(hook.get("allowed_env_vars") or [])
                        if str(value).strip()
                    ],
                    supported=bool(hook.get("supported")),
                    unsupported_reasons=[
                        str(reason).strip()
                        for reason in list(hook.get("unsupported_reasons") or [])
                        if str(reason).strip()
                    ],
                    required_secrets=required_secrets,
                    source=source,
                    order=int(hook.get("order") or 0),
                    raw=copy.deepcopy(dict(hook.get("raw") or {})),
                )
                if hook_handler.required_secrets:
                    missing_secrets.extend(hook_handler.required_secrets)
                    blocked_reasons.append(
                        f"Missing secrets for {hook_handler.event}: "
                        + ", ".join(hook_handler.required_secrets)
                    )
                if not hook_handler.supported:
                    blocked_reasons.extend(hook_handler.unsupported_reasons)
                if hook_handler.supported and not hook_handler.required_secrets:
                    handlers_by_event.setdefault(hook_handler.event, []).append(hook_handler)
                    registered_handler_count += 1

        return RegisteredHookInstall(
            install_id=install_id,
            install_root=str(install_root_path),
            plugin_data_dir=str(plugin_data_dir),
            enabled=bool(install.get("enabled")),
            normalized_hooks=copy.deepcopy(normalized_hooks),
            handlers_by_event=handlers_by_event,
            supported_event_count=int(normalized_hooks.get("supported_event_count") or 0),
            unsupported_event_count=int(normalized_hooks.get("unsupported_event_count") or 0),
            supported_types=list(normalized_hooks.get("supported_types") or []),
            unsupported_types=list(normalized_hooks.get("unsupported_types") or []),
            missing_secrets=_unique_str_list(missing_secrets),
            blocked_reasons=_unique_str_list(
                blocked_reasons + list(normalized_hooks.get("compatibility_warnings") or [])
            ),
            registered_handler_count=registered_handler_count,
            compatibility_warnings=list(normalized_hooks.get("compatibility_warnings") or []),
        )

    def _install_substitutions(self, install: dict[str, Any]) -> dict[str, str]:
        install_id = str(install.get("id") or "")
        install_root = str(install.get("install_root") or "")
        plugin_data_dir = str(MARKETPLACE_PLUGIN_DATA_DIR / install_id)
        substitutions = {
            "XPDITE_MARKETPLACE_ROOT": install_root,
            "CLAUDE_PLUGIN_ROOT": install_root,
            "CLAUDE_PLUGIN_DATA": plugin_data_dir,
        }
        try:
            from ..marketplace.service import get_marketplace_service

            substitutions.update(get_marketplace_service().get_install_secrets(install_id))
        except Exception:
            logger.exception("Failed to resolve marketplace secrets for hook install %s", install_id)
        hook_manifest = (install.get("component_manifest") or {}).get("hooks")
        if isinstance(hook_manifest, dict):
            for entry in list(hook_manifest.get("user_config") or []):
                if not isinstance(entry, dict):
                    continue
                key = _normalize_user_config_key(str(entry.get("key") or ""))
                if not key:
                    continue
                value = str(substitutions.get(key) or "")
                if not value:
                    continue
                substitutions.setdefault(f"user_config.{key}", value)
                substitutions.setdefault(_user_config_env_var(key), value)
        return substitutions

    def _ensure_hook_session(
        self,
        tab_state: "TabState",
        *,
        force_new_session: bool = False,
    ) -> dict[str, Any]:
        if force_new_session or not tab_state.hook_session:
            session_id = str(uuid.uuid4())
            transcript_path = MARKETPLACE_HOOK_TRANSCRIPTS_DIR / f"{tab_state.tab_id}-{session_id}.jsonl"
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript_path.touch(exist_ok=True)
            tab_state.hook_session = {
                "session_id": session_id,
                "transcript_path": str(transcript_path),
                "stop_hook_active": False,
                "started": False,
                "start_source": "startup",
            }
        return tab_state.hook_session

    def _build_common_payload(
        self,
        tab_state: Optional["TabState"],
        hook_event_name: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "hook_event_name": hook_event_name,
            "cwd": str(PROJECT_ROOT),
            "permission_mode": "default",
        }
        if tab_state is None:
            return payload
        session = self._ensure_hook_session(tab_state)
        payload.update(
            {
                "session_id": session["session_id"],
                "transcript_path": session["transcript_path"],
                "xpdite_tab_id": tab_state.tab_id,
            }
        )
        return payload

    def _build_tool_payload(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        server_name: str,
    ) -> dict[str, Any]:
        canonical_name = _TOOL_NAME_ALIASES.get(tool_name, tool_name)
        canonical_input = self._canonicalize_tool_input(canonical_name, tool_input)
        return {
            "tool_name": canonical_name,
            "tool_input": canonical_input,
            "xpdite_tool_name": tool_name,
            "xpdite_tool_input": copy.deepcopy(tool_input),
            "xpdite_server_name": server_name,
        }

    def _canonicalize_tool_input(
        self,
        canonical_tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = copy.deepcopy(tool_input)
        for source_key, target_key in _TOOL_INPUT_FIELD_ALIASES.items():
            if source_key in normalized and target_key not in normalized:
                normalized[target_key] = normalized[source_key]
        if canonical_tool_name == "Bash" and "command" in normalized:
            normalized.setdefault("command", normalized.get("command"))
        return normalized

    def _current_tab_state(self) -> Optional["TabState"]:
        try:
            from ...core.connection import get_current_tab_id
            from ..chat.tab_manager_instance import tab_manager

            tab_id = get_current_tab_id()
            if not tab_id or tab_manager is None:
                return None
            session = tab_manager.get_session(tab_id)
            return session.state if session else None
        except Exception:
            logger.exception("Failed to resolve current tab state for hooks")
            return None

    async def _dispatch_event(
        self,
        event_name: str,
        payload: dict[str, Any],
        *,
        tab_state: Optional["TabState"],
    ) -> HookDispatchResult:
        matched_handlers = self._matched_handlers(event_name, payload)
        if not matched_handlers:
            return HookDispatchResult()

        tasks = [
            self._execute_handler(handler, payload)
            for handler in matched_handlers
        ]
        execution_results = await asyncio.gather(*tasks, return_exceptions=False)
        dispatch_result = HookDispatchResult()

        for handler, result in sorted(
            zip(matched_handlers, execution_results, strict=False),
            key=lambda item: item[0].order,
        ):
            self._apply_execution_result(handler, result, event_name, dispatch_result)

        if dispatch_result.conflicts:
            for handler in matched_handlers:
                self._record_runtime_message(
                    handler.install_id,
                    "Conflicting hook outputs were resolved in manifest order.",
                )

        return dispatch_result

    def _matched_handlers(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> list[HookHandler]:
        matched: list[HookHandler] = []
        dedupe_keys: set[tuple[str, str, str]] = set()
        tool_name = str(payload.get("tool_name") or "").strip()
        xpdite_tool_name = str(payload.get("xpdite_tool_name") or "").strip()
        tool_input = dict(payload.get("tool_input") or {})
        tool_names = {name for name in (tool_name, xpdite_tool_name) if name}

        for state in self._registered_installs.values():
            for handler in state.handlers_by_event.get(event_name, []):
                match_value = tool_name if event_name.startswith("Post") or event_name == "PreToolUse" else event_name
                if event_name in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
                    if not _matcher_matches(handler.matcher, tool_name):
                        if not _matcher_matches(handler.matcher, xpdite_tool_name):
                            continue
                    if handler.condition and not _permission_rule_matches(handler.condition, tool_names, tool_input):
                        continue
                elif not _matcher_matches(handler.matcher, match_value):
                    continue

                dedupe_value = handler.command or handler.url or handler.hook_id
                dedupe_key = (handler.install_id, handler.hook_type, dedupe_value)
                if dedupe_key in dedupe_keys:
                    continue
                dedupe_keys.add(dedupe_key)
                matched.append(handler)

        return matched

    async def _execute_handler(
        self,
        handler: HookHandler,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        install_state = self._registered_installs.get(handler.install_id)
        if install_state is None:
            return {"error": "Hook install is not registered."}
        substitutions = self._install_substitutions(
            {
                "id": handler.install_id,
                "install_root": install_state.install_root,
                "component_manifest": {"hooks": install_state.normalized_hooks},
            }
        )
        env_map = {
            **os.environ,
            **substitutions,
        }
        if handler.hook_type == "command":
            return await self._execute_command_hook(handler, payload, env_map)
        if handler.hook_type == "http":
            return await self._execute_http_hook(handler, payload, env_map)
        return {"error": f"Unsupported hook type '{handler.hook_type}'."}

    async def _execute_command_hook(
        self,
        handler: HookHandler,
        payload: dict[str, Any],
        env_map: dict[str, str],
    ) -> dict[str, Any]:
        command = _substitute_placeholders(str(handler.command or ""), env_map)
        if handler.shell == "powershell":
            argv = ["powershell", "-NoProfile", "-Command", command]
        elif handler.shell == "bash":
            argv = ["bash", "-lc", command]
        elif os.name == "nt":
            argv = ["cmd", "/d", "/s", "/c", command]
        else:
            argv = ["sh", "-lc", command]

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=env_map.get("CLAUDE_PLUGIN_ROOT") or None,
                env=env_map,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(_json_dumps(payload).encode("utf-8")),
                timeout=handler.timeout_seconds,
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            try:
                await process.wait()
            except Exception:
                pass
            return {"timeout": True, "stderr": f"Hook timed out after {handler.timeout_seconds:.0f}s."}
        except Exception as exc:
            return {"error": f"Failed to launch command hook: {exc}"}

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        parsed_json = None
        if stdout:
            try:
                parsed_json = json.loads(stdout)
            except json.JSONDecodeError:
                parsed_json = None
        return {
            "return_code": int(process.returncode),
            "stdout": stdout,
            "stderr": stderr,
            "json": parsed_json if isinstance(parsed_json, dict) else None,
        }

    async def _execute_http_hook(
        self,
        handler: HookHandler,
        payload: dict[str, Any],
        env_map: dict[str, str],
    ) -> dict[str, Any]:
        url = _substitute_placeholders(str(handler.url or ""), env_map)
        headers = {
            key: _interpolate_allowed_env_vars(
                _substitute_placeholders(value, env_map),
                handler.allowed_env_vars,
                env_map,
            )
            for key, value in handler.headers.items()
        }

        def _post() -> requests.Response:
            return requests.post(
                url,
                json=payload,
                headers=headers or None,
                timeout=handler.timeout_seconds,
            )

        try:
            response = await asyncio.to_thread(_post)
        except requests.Timeout:
            return {"timeout": True, "stderr": f"HTTP hook timed out after {handler.timeout_seconds:.0f}s."}
        except Exception as exc:
            return {"error": f"HTTP hook request failed: {exc}"}

        body = response.text.strip()
        parsed_json = None
        if body:
            try:
                parsed_json = response.json()
            except ValueError:
                parsed_json = None
        return {
            "return_code": response.status_code,
            "stdout": body,
            "stderr": "" if response.ok else body[:500],
            "json": parsed_json if isinstance(parsed_json, dict) else None,
            "http_ok": response.ok,
        }

    def _apply_execution_result(
        self,
        handler: HookHandler,
        execution_result: dict[str, Any],
        event_name: str,
        dispatch_result: HookDispatchResult,
    ) -> None:
        if execution_result.get("timeout"):
            message = str(execution_result.get("stderr") or "Hook timed out.")
            dispatch_result.runtime_messages.append(message)
            self._record_runtime_message(handler.install_id, message)
            return
        if execution_result.get("error"):
            message = str(execution_result.get("error") or "Hook failed.")
            dispatch_result.runtime_messages.append(message)
            self._record_runtime_message(handler.install_id, message)
            return

        return_code = int(execution_result.get("return_code") or 0)
        is_http = handler.hook_type == "http"
        if is_http and not execution_result.get("http_ok"):
            message = str(execution_result.get("stderr") or "HTTP hook returned a non-2xx response.")
            dispatch_result.runtime_messages.append(message)
            self._record_runtime_message(handler.install_id, message)
            return
        if not is_http and return_code not in {0, 2}:
            message = str(execution_result.get("stderr") or f"Hook exited with code {return_code}.")
            dispatch_result.runtime_messages.append(message)
            self._record_runtime_message(handler.install_id, message)
            return

        payload = execution_result.get("json") if isinstance(execution_result.get("json"), dict) else {}
        hook_payload = dict(payload.get("hookSpecificOutput") or {}) if isinstance(payload.get("hookSpecificOutput"), dict) else {}
        merged_payload = {**payload, **hook_payload}
        stderr = str(execution_result.get("stderr") or "").strip()
        block_reason = (
            str(merged_payload.get("reason") or merged_payload.get("stopReason") or "").strip()
            or stderr
        )

        if merged_payload.get("systemMessage") and not dispatch_result.suppress_output:
            dispatch_result.system_messages.append(str(merged_payload["systemMessage"]).strip())
        if merged_payload.get("additionalContext") and not dispatch_result.suppress_output:
            dispatch_result.additional_context.append(str(merged_payload["additionalContext"]).strip())
        if bool(merged_payload.get("suppressOutput")):
            dispatch_result.suppress_output = True
        if merged_payload.get("continue") is False and event_name in _BLOCKING_EVENTS and not dispatch_result.blocked:
            dispatch_result.blocked = True
            dispatch_result.reason = block_reason or "Blocked by Claude-compatible hook."
            dispatch_result.continue_processing = False

        if return_code == 2 and event_name in _BLOCKING_EVENTS and not dispatch_result.blocked:
            dispatch_result.blocked = True
            dispatch_result.reason = block_reason or "Blocked by Claude-compatible hook."
            dispatch_result.continue_processing = False

        if event_name == "UserPromptSubmit":
            if str(merged_payload.get("decision") or "").strip().lower() == "block" and not dispatch_result.blocked:
                dispatch_result.blocked = True
                dispatch_result.reason = block_reason or "Blocked by Claude-compatible hook."
                dispatch_result.continue_processing = False
            return

        if event_name == "PreToolUse":
            permission_decision = str(merged_payload.get("permissionDecision") or "").strip().lower()
            if permission_decision in {"ask", "defer"}:
                dispatch_result.blocked = True
                dispatch_result.reason = (
                    f"Unsupported Claude-compatible PreToolUse permissionDecision '{permission_decision}' in Xpdite."
                )
                dispatch_result.continue_processing = False
                self._record_runtime_message(handler.install_id, dispatch_result.reason)
                return
            if permission_decision == "deny" and not dispatch_result.blocked:
                dispatch_result.blocked = True
                dispatch_result.reason = block_reason or str(
                    merged_payload.get("permissionDecisionReason") or "Blocked by Claude-compatible hook."
                )
                dispatch_result.permission_decision = permission_decision
                dispatch_result.permission_decision_reason = str(
                    merged_payload.get("permissionDecisionReason") or ""
                ).strip() or None
                dispatch_result.continue_processing = False
            elif permission_decision == "allow" and dispatch_result.permission_decision not in {"allow", "deny"}:
                dispatch_result.permission_decision = permission_decision
                dispatch_result.permission_decision_reason = str(
                    merged_payload.get("permissionDecisionReason") or ""
                ).strip() or None

            updated_input = merged_payload.get("updatedInput")
            if isinstance(updated_input, dict):
                if dispatch_result.updated_input is None:
                    dispatch_result.updated_input = copy.deepcopy(updated_input)
                elif dispatch_result.updated_input != updated_input:
                    dispatch_result.conflicts.append("Conflicting updatedInput values from PreToolUse hooks.")
            return

        if event_name in {"PostToolUse", "PostToolUseFailure"}:
            if str(merged_payload.get("decision") or "").strip().lower() == "block" and not dispatch_result.blocked:
                dispatch_result.blocked = True
                dispatch_result.reason = block_reason or "Blocked by Claude-compatible hook."
                dispatch_result.continue_processing = False
            updated_output = merged_payload.get("updatedMCPToolOutput")
            if event_name == "PostToolUse" and updated_output is not None:
                if dispatch_result.updated_mcp_tool_output is None:
                    dispatch_result.updated_mcp_tool_output = copy.deepcopy(updated_output)
                elif dispatch_result.updated_mcp_tool_output != updated_output:
                    dispatch_result.conflicts.append(
                        "Conflicting updatedMCPToolOutput values from PostToolUse hooks."
                    )
            return

        if event_name == "Stop":
            if str(merged_payload.get("decision") or "").strip().lower() == "block" and not dispatch_result.blocked:
                dispatch_result.blocked = True
                dispatch_result.reason = block_reason or "Blocked by Claude-compatible hook."
                dispatch_result.continue_processing = False

    def _record_runtime_message(self, install_id: str, message: str) -> None:
        if not message:
            return
        state = self._registered_installs.get(install_id)
        if state is not None:
            state.last_runtime_error = message


_instance: Optional[HooksRuntime] = None


def get_hooks_runtime() -> HooksRuntime:
    global _instance
    if _instance is None:
        _instance = HooksRuntime()
    return _instance

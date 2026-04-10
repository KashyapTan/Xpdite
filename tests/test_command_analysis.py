"""Tests for source/services/shell/command_analysis.py."""

from unittest.mock import patch

from source.services.shell import command_analysis


class TestResolveShellAutoWindows:
    def test_prefers_powershell_for_cmdlet_syntax(self, monkeypatch):
        monkeypatch.setattr(command_analysis, "_IS_WINDOWS", True)
        monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

        with patch.object(
            command_analysis,
            "_resolve_powershell_executable",
            return_value=r"C:\Program Files\PowerShell\7\pwsh.exe",
        ):
            resolved = command_analysis.resolve_shell(
                "auto",
                "Get-ChildItem -Force",
            )

        assert resolved.name == "powershell"

    def test_prefers_bash_for_clear_posix_syntax_when_available(self, monkeypatch):
        monkeypatch.setattr(command_analysis, "_IS_WINDOWS", True)
        monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

        def _which(name: str) -> str | None:
            if name == "bash":
                return r"C:\Program Files\Git\bin\bash.exe"
            return None

        with (
            patch.object(command_analysis, "_resolve_powershell_executable", return_value=None),
            patch.object(command_analysis.shutil, "which", side_effect=_which),
        ):
            resolved = command_analysis.resolve_shell(
                "auto",
                "grep -n needle README.md | head -n 1",
            )

        assert resolved.name == "bash"

    def test_falls_back_to_cmd_for_generic_windows_commands(self, monkeypatch):
        monkeypatch.setattr(command_analysis, "_IS_WINDOWS", True)
        monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

        with patch.object(command_analysis, "_resolve_powershell_executable", return_value=None):
            resolved = command_analysis.resolve_shell("auto", "echo hello")

        assert resolved.name == "cmd"

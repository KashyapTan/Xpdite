"""Tests for mcp_servers/servers/terminal/blocklist.py."""

from mcp_servers.servers.terminal.blocklist import check_blocklist, check_path_injection


class TestCheckBlocklist:
    def test_safe_command(self):
        blocked, reason = check_blocklist("echo hello")
        assert blocked is False
        assert reason == ""

    def test_safe_git_command(self):
        blocked, _ = check_blocklist("git status")
        assert blocked is False

    def test_rm_rf_root(self):
        blocked, reason = check_blocklist("rm -rf / ")
        assert blocked is True
        assert reason  # non-empty reason

    def test_format_drive(self):
        blocked, reason = check_blocklist("format C:")
        assert blocked is True

    def test_dd_to_dev(self):
        blocked, reason = check_blocklist("dd if=/dev/zero of=/dev/sda bs=1M")
        assert blocked is True

    def test_mkfs(self):
        blocked, reason = check_blocklist("mkfs.ext4 /dev/sda1")
        assert blocked is True

    def test_normal_python_command(self):
        blocked, _ = check_blocklist("python main.py --port 8000")
        assert blocked is False

    def test_npm_install(self):
        blocked, _ = check_blocklist("npm install react")
        assert blocked is False

    def test_rd_windows_system(self):
        blocked, reason = check_blocklist("rd /s /q C:\\Windows")
        assert blocked is True
        assert reason

    def test_del_windows_system(self):
        blocked, reason = check_blocklist("del /f C:\\Windows\\System32\\config")
        assert blocked is True
        assert reason

    def test_reg_delete_hklm(self):
        blocked, reason = check_blocklist("reg delete HKLM\\SOFTWARE\\Microsoft")
        assert blocked is True
        assert reason

    def test_reg_delete_hkcu(self):
        blocked, reason = check_blocklist("reg delete HKCU\\Environment")
        assert blocked is True
        assert reason


class TestCheckPathInjection:
    def test_none_env(self):
        injected, reason = check_path_injection(None)
        assert injected is False

    def test_clean_env(self):
        injected, _ = check_path_injection({"HOME": "/home/user", "LANG": "en_US"})
        assert injected is False

    def test_path_override_rejected(self):
        injected, reason = check_path_injection({"PATH": "/malicious/bin:/usr/bin"})
        assert injected is True
        assert "PATH" in reason

    def test_path_case_variants(self):
        injected, _ = check_path_injection({"Path": "C:\\evil"})
        assert injected is True

        injected, _ = check_path_injection({"path": "/evil"})
        assert injected is True

    def test_empty_env(self):
        injected, _ = check_path_injection({})
        assert injected is False

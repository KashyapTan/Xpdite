from mcp_servers.servers.terminal import server as terminal_server


def test_find_files_rejects_directory_outside_default_cwd(tmp_path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()
    (allowed_root / "example.py").write_text("print('ok')", encoding="utf-8")

    monkeypatch.setattr(terminal_server, "_DEFAULT_CWD", str(allowed_root))

    result = terminal_server.find_files("*.py", str(outside_root))

    assert "restricted to the current working directory tree" in result

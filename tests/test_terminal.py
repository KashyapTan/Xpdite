"""Tests for TerminalService._decode_safe_escapes."""

from source.services.terminal import TerminalService


class TestDecodeSafeEscapes:
    def test_newline(self):
        assert TerminalService._decode_safe_escapes("hello\\nworld") == "hello\nworld"

    def test_carriage_return(self):
        assert TerminalService._decode_safe_escapes("line\\r") == "line\r"

    def test_tab(self):
        assert TerminalService._decode_safe_escapes("col1\\tcol2") == "col1\tcol2"

    def test_backslash(self):
        assert TerminalService._decode_safe_escapes("foo\\\\bar") == "foo\\bar"

    def test_hex_escape(self):
        # \x03 = ETX (Ctrl-C)
        assert TerminalService._decode_safe_escapes("\\x03") == "\x03"

    def test_hex_escape_esc(self):
        # \x1b = ESC character
        assert TerminalService._decode_safe_escapes("\\x1b") == "\x1b"

    def test_hex_escape_uppercase(self):
        assert TerminalService._decode_safe_escapes("\\x4F") == "\x4f"

    def test_mixed_escapes(self):
        result = TerminalService._decode_safe_escapes("a\\nb\\tc\\\\d\\x41")
        assert result == "a\nb\tc\\d\x41"  # \x41 = 'A'

    def test_no_escapes(self):
        assert TerminalService._decode_safe_escapes("plain text") == "plain text"

    def test_empty_string(self):
        assert TerminalService._decode_safe_escapes("") == ""

    def test_non_whitelisted_escape_passes_through(self):
        """Escapes not in the whitelist should be left as-is."""
        result = TerminalService._decode_safe_escapes("\\a\\b")
        # \a and \b are NOT in the whitelist, so they stay literal
        assert result == "\\a\\b"

    def test_multiple_newlines(self):
        assert TerminalService._decode_safe_escapes("a\\n\\n\\nb") == "a\n\n\nb"

"""Tests for source/llm/prompt.py — system prompt builder."""


from source.llm.prompt import build_system_prompt, _get_datetime, _get_os_info, _BASE_TEMPLATE


class TestGetDatetime:
    def test_returns_string(self):
        result = _get_datetime()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_weekday(self):
        """Should contain a weekday name like Monday, Tuesday, etc."""
        result = _get_datetime()
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        assert any(d in result for d in weekdays)

    def test_contains_year(self):
        result = _get_datetime()
        # Should contain a 4-digit year
        import re
        assert re.search(r"\d{4}", result)


class TestGetOsInfo:
    def test_returns_string(self):
        result = _get_os_info()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_platform(self):
        import platform
        result = _get_os_info()
        system = platform.system()
        if system == "Windows":
            assert "Windows" in result
        elif system == "Darwin":
            assert "macOS" in result
        else:
            assert "Linux" in result

    def test_contains_machine(self):
        import platform
        result = _get_os_info()
        assert platform.machine() in result


class TestBuildSystemPrompt:
    def test_default_prompt_contains_xpdite(self):
        prompt = build_system_prompt()
        assert "Xpdite" in prompt

    def test_datetime_substituted(self):
        prompt = build_system_prompt()
        assert "{{current_datetime}}" not in prompt

    def test_os_info_substituted(self):
        prompt = build_system_prompt()
        assert "{{os_info}}" not in prompt

    def test_skills_block_empty_by_default(self):
        prompt = build_system_prompt()
        assert "{{skills_block}}" not in prompt

    def test_skills_block_injected(self):
        skills = "\n\n## Active Skills\n\nUse terminal for file operations.\n"
        prompt = build_system_prompt(skills_block=skills)
        assert "Use terminal for file operations." in prompt

    def test_file_search_policy_is_present(self):
        prompt = build_system_prompt()
        assert "glob_files" in prompt
        assert "grep_files" in prompt
        assert "Do NOT use `run_command`" in prompt
        assert "searching inside archives" in prompt

    def test_custom_template(self):
        template = "You are a test assistant. Today is {{current_datetime}}. OS: {{os_info}}.{{skills_block}}"
        prompt = build_system_prompt(template=template)
        assert "test assistant" in prompt
        assert "{{current_datetime}}" not in prompt
        assert "{{os_info}}" not in prompt

    def test_empty_template_uses_default(self):
        prompt = build_system_prompt(template="   ")
        assert "Xpdite" in prompt

    def test_none_template_uses_default(self):
        prompt = build_system_prompt(template=None)
        assert "Xpdite" in prompt

    def test_base_template_has_placeholders(self):
        assert "{{current_datetime}}" in _BASE_TEMPLATE
        assert "{{os_info}}" in _BASE_TEMPLATE
        assert "{{skills_block}}" in _BASE_TEMPLATE

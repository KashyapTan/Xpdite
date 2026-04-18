"""Tests for source/mcp_integration/executors/scheduler_executor.py."""

from unittest.mock import AsyncMock, patch

import pytest

from source.mcp_integration.executors.scheduler_executor import (
    execute_scheduler_tool,
    is_scheduler_tool,
)


class TestIsSchedulerTool:
    def test_matches_supported_scheduler_tools(self):
        assert is_scheduler_tool("create_job", "scheduler") is True
        assert is_scheduler_tool("list_jobs", "scheduler") is True
        assert is_scheduler_tool("run_job_now", "scheduler") is True

    def test_rejects_unknown_tools_or_servers(self):
        assert is_scheduler_tool("create_job", "memory") is False
        assert is_scheduler_tool("unknown", "scheduler") is False


class TestExecuteSchedulerTool:
    @pytest.mark.asyncio
    async def test_create_job_validates_required_fields(self):
        assert (
            await execute_scheduler_tool("create_job", {}, "scheduler")
            == "Error: 'name' is required"
        )
        assert (
            await execute_scheduler_tool(
                "create_job",
                {"name": "Job", "cron_expression": "* * * * *", "instruction": "hi"},
                "scheduler",
            )
            == "Error: 'timezone' is required"
        )

    @pytest.mark.asyncio
    async def test_create_job_rejects_invalid_timezone(self):
        result = await execute_scheduler_tool(
            "create_job",
            {
                "name": "Job",
                "cron_expression": "* * * * *",
                "instruction": "hi",
                "timezone": "Mars/Base",
            },
            "scheduler",
        )

        assert "Error: Invalid timezone 'Mars/Base'" in result

    @pytest.mark.asyncio
    async def test_create_job_formats_success_output(self):
        created = {
            "id": "job-1",
            "name": "Morning Digest",
            "next_run_at": 1735732800,
        }
        with (
            patch(
                "source.services.scheduling.scheduler.scheduler_service.create_job",
                new_callable=AsyncMock,
                return_value=created,
            ) as mock_create,
            patch(
                "source.mcp_integration.executors.scheduler_executor.get_current_model",
                return_value="openai/gpt-4o",
            ),
        ):
            result = await execute_scheduler_tool(
                "create_job",
                {
                    "name": "Morning Digest",
                    "cron_expression": "0 9 * * *",
                    "instruction": "Summarize today's work",
                    "timezone": "America/New_York",
                },
                "scheduler",
            )

        assert "Successfully created scheduled job:" in result
        assert "Morning Digest" in result
        assert "openai/gpt-4o" in result
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_jobs_handles_empty_and_formats_jobs(self):
        with patch(
            "source.services.scheduling.scheduler.scheduler_service.list_jobs",
            return_value=[],
        ):
            empty = await execute_scheduler_tool("list_jobs", {}, "scheduler")
        assert empty.startswith("No scheduled jobs configured.")

        with patch(
            "source.services.scheduling.scheduler.scheduler_service.list_jobs",
            return_value=[
                {
                    "id": "job-1",
                    "name": "Digest",
                    "enabled": False,
                    "cron_expression": "0 9 * * *",
                    "timezone": "America/New_York",
                    "next_run_at": 1735732800,
                    "last_run_at": 1735646400,
                    "run_count": 4,
                    "is_one_shot": True,
                }
            ],
        ):
            result = await execute_scheduler_tool("list_jobs", {}, "scheduler")

        assert "Scheduled Jobs:" in result
        assert "Digest [Paused]" in result
        assert "Type: One-shot" in result

    @pytest.mark.asyncio
    async def test_delete_pause_resume_and_run_now_cover_success_and_missing_cases(self):
        with patch(
            "source.services.scheduling.scheduler.scheduler_service.get_job",
            return_value=None,
        ):
            assert (
                await execute_scheduler_tool(
                    "delete_job", {"job_id": "missing"}, "scheduler"
                )
                == "Error: Job with ID 'missing' not found"
            )
            assert (
                await execute_scheduler_tool(
                    "run_job_now", {"job_id": "missing"}, "scheduler"
                )
                == "Error: Job with ID 'missing' not found"
            )

        with (
            patch(
                "source.services.scheduling.scheduler.scheduler_service.get_job",
                return_value={"id": "job-1", "name": "Digest", "timezone": "UTC"},
            ),
            patch(
                "source.services.scheduling.scheduler.scheduler_service.delete_job",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            assert (
                await execute_scheduler_tool(
                    "delete_job", {"job_id": "job-1"}, "scheduler"
                )
                == "Successfully deleted job: Digest"
            )

        with patch(
            "source.services.scheduling.scheduler.scheduler_service.pause_job",
            new_callable=AsyncMock,
            return_value={"id": "job-1", "name": "Digest"},
        ):
            assert (
                await execute_scheduler_tool(
                    "pause_job", {"job_id": "job-1"}, "scheduler"
                )
                == "Successfully paused job: Digest"
            )

        with patch(
            "source.services.scheduling.scheduler.scheduler_service.resume_job",
            new_callable=AsyncMock,
            return_value={
                "id": "job-1",
                "name": "Digest",
                "timezone": "UTC",
                "next_run_at": 1735732800,
            },
        ):
            resumed = await execute_scheduler_tool(
                "resume_job", {"job_id": "job-1"}, "scheduler"
            )
        assert resumed.startswith("Successfully resumed job: Digest")
        assert "Next run:" in resumed

        with (
            patch(
                "source.services.scheduling.scheduler.scheduler_service.get_job",
                return_value={"id": "job-1", "name": "Digest"},
            ),
            patch(
                "source.services.scheduling.scheduler.scheduler_service.run_job_now",
                new_callable=AsyncMock,
                return_value="conv-1",
            ),
        ):
            run_now = await execute_scheduler_tool(
                "run_job_now", {"job_id": "job-1"}, "scheduler"
            )
        assert "Successfully triggered job: Digest" in run_now
        assert "Conversation ID: conv-1" in run_now

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_clear_message(self):
        result = await execute_scheduler_tool("unknown", {}, "scheduler")
        assert result == "Unknown scheduler tool: unknown"

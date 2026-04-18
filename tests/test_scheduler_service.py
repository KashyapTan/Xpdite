"""Tests for source/services/scheduling/scheduler.py."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from source.services.scheduling.scheduler import SchedulerService


@pytest.fixture()
def scheduler_service():
    return SchedulerService()


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_loads_enabled_jobs_and_starts_scheduler(self, scheduler_service):
        scheduler = MagicMock()
        jobs = [
            {"id": "job-1", "name": "Morning"},
            {"id": "job-2", "name": "Evening"},
        ]

        with (
            patch(
                "source.services.scheduling.scheduler.AsyncIOScheduler",
                return_value=scheduler,
            ),
            patch(
                "source.services.scheduling.scheduler.db.list_scheduled_jobs",
                return_value=jobs,
            ),
            patch.object(scheduler_service, "_schedule_job") as schedule_job,
        ):
            await scheduler_service.start()

        assert scheduler_service._scheduler is scheduler
        assert scheduler_service._running is True
        schedule_job.assert_has_calls([call(jobs[0]), call(jobs[1])])
        scheduler.start.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_stop_cancels_active_jobs_and_shuts_down(self, scheduler_service):
        async def _hang():
            await asyncio.sleep(60)

        task = asyncio.create_task(_hang())
        scheduler = MagicMock()
        scheduler_service._running = True
        scheduler_service._scheduler = scheduler
        scheduler_service._active_jobs["job-1"] = task

        await scheduler_service.stop()

        assert task.done() is True
        assert scheduler_service._running is False
        scheduler.shutdown.assert_called_once_with(wait=False)


class TestSchedulerScheduling:
    def test_schedule_job_registers_trigger_and_persists_next_run(
        self, scheduler_service
    ):
        next_fire = datetime(2026, 4, 18, 9, 0, tzinfo=timezone.utc)
        trigger = MagicMock()
        trigger.get_next_fire_time.return_value = next_fire
        scheduler_service._scheduler = MagicMock()

        job = {
            "id": "job-1",
            "name": "Morning Digest",
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        }

        with (
            patch(
                "source.services.scheduling.scheduler.CronTrigger.from_crontab",
                return_value=trigger,
            ),
            patch("source.services.scheduling.scheduler.db.update_scheduled_job") as update_job,
        ):
            scheduler_service._schedule_job(job)

        scheduler_service._scheduler.add_job.assert_called_once()
        update_job.assert_called_once_with("job-1", next_run_at=next_fire.timestamp())

    def test_schedule_job_logs_and_skips_invalid_cron(self, scheduler_service):
        scheduler_service._scheduler = MagicMock()
        job = {
            "id": "job-1",
            "name": "Morning Digest",
            "cron_expression": "invalid",
            "timezone": "UTC",
        }

        with (
            patch(
                "source.services.scheduling.scheduler.CronTrigger.from_crontab",
                side_effect=ValueError("bad cron"),
            ),
            patch("source.services.scheduling.scheduler.logger") as logger_mock,
        ):
            scheduler_service._schedule_job(job)

        scheduler_service._scheduler.add_job.assert_not_called()
        logger_mock.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_job_validates_cron_and_schedules_when_running(
        self, scheduler_service
    ):
        next_fire = datetime(2026, 4, 18, 9, 0, tzinfo=timezone.utc)
        trigger = MagicMock()
        trigger.get_next_fire_time.return_value = next_fire
        created_job = {
            "id": "job-1",
            "name": "Morning Digest",
            "cron_expression": "0 9 * * *",
            "instruction": "Summarize",
            "timezone": "UTC",
            "model": "openai/gpt-4o",
        }
        scheduler_service._running = True

        with (
            patch(
                "source.services.scheduling.scheduler.CronTrigger.from_crontab",
                return_value=trigger,
            ),
            patch(
                "source.services.scheduling.scheduler.db.create_scheduled_job",
                return_value=created_job,
            ) as create_job,
            patch.object(scheduler_service, "_schedule_job") as schedule_job,
        ):
            result = await scheduler_service.create_job(
                name="Morning Digest",
                cron_expression="0 9 * * *",
                instruction="Summarize",
                timezone="UTC",
                model="openai/gpt-4o",
            )

        assert result is created_job
        create_job.assert_called_once()
        schedule_job.assert_called_once_with(created_job)

    @pytest.mark.asyncio
    async def test_create_job_raises_on_invalid_cron(self, scheduler_service):
        with patch(
            "source.services.scheduling.scheduler.CronTrigger.from_crontab",
            side_effect=ValueError("bad cron"),
        ):
            with pytest.raises(ValueError, match="Invalid cron expression"):
                await scheduler_service.create_job(
                    name="Broken",
                    cron_expression="bad",
                    instruction="hi",
                    timezone="UTC",
                )

    @pytest.mark.asyncio
    async def test_delete_job_removes_scheduler_entry_and_cancels_active_task(
        self, scheduler_service
    ):
        scheduler_service._scheduler = MagicMock()

        async def _hang():
            await asyncio.sleep(60)

        task = asyncio.create_task(_hang())
        scheduler_service._active_jobs["job-1"] = task
        job = {"id": "job-1", "name": "Digest"}

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch("source.services.scheduling.scheduler.db.delete_scheduled_job") as delete_job,
        ):
            result = await scheduler_service.delete_job("job-1")
            await asyncio.sleep(0)

        assert result is True
        scheduler_service._scheduler.remove_job.assert_called_once_with("job-1")
        delete_job.assert_called_once_with("job-1")
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_pause_and_resume_jobs_refresh_scheduler_metadata(self, scheduler_service):
        scheduler_service._scheduler = MagicMock()
        scheduler_service._running = True
        job = {"id": "job-1", "name": "Digest", "enabled": True}
        paused_job = {**job, "enabled": False, "next_run_at": None}
        resumed_job = {**job, "enabled": True, "next_run_at": 123.0}

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch(
                "source.services.scheduling.scheduler.db.update_scheduled_job",
                side_effect=[paused_job, resumed_job],
            ) as update_job,
            patch.object(
                scheduler_service,
                "_reschedule_job",
                AsyncMock(return_value=resumed_job),
            ) as reschedule_job,
        ):
            paused = await scheduler_service.pause_job("job-1")
            resumed = await scheduler_service.resume_job("job-1")

        scheduler_service._scheduler.remove_job.assert_called_once_with("job-1")
        update_job.assert_any_call("job-1", enabled=False, next_run_at=None)
        update_job.assert_any_call("job-1", enabled=True)
        reschedule_job.assert_awaited_once_with("job-1")
        assert paused == paused_job
        assert resumed == resumed_job


class TestSchedulerExecution:
    @pytest.mark.asyncio
    async def test_execute_job_skips_missing_or_disabled_jobs(self, scheduler_service):
        with patch(
            "source.services.scheduling.scheduler.db.get_scheduled_job",
            side_effect=[None, {"id": "job-1", "name": "Digest", "enabled": False}],
        ):
            await scheduler_service._execute_job("missing")
            await scheduler_service._execute_job("job-1")

        assert scheduler_service._active_jobs == {}

    @pytest.mark.asyncio
    async def test_execute_job_handles_one_shot_completion(self, scheduler_service):
        scheduler_service._scheduler = MagicMock()
        job = {
            "id": "job-1",
            "name": "Digest",
            "enabled": True,
            "is_one_shot": True,
            "timezone": "UTC",
            "cron_expression": "0 9 * * *",
        }

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch.object(
                scheduler_service, "_run_job_query", AsyncMock(return_value="conv-1")
            ),
            patch(
                "source.services.scheduling.scheduler.db.mark_job_run"
            ) as mark_run,
            patch(
                "source.services.scheduling.scheduler.db.update_scheduled_job"
            ) as update_job,
            patch.object(
                scheduler_service, "_create_job_notification", AsyncMock()
            ) as create_notification,
            patch.object(
                scheduler_service, "_deliver_to_platform", AsyncMock()
            ) as deliver_to_platform,
        ):
            await scheduler_service._execute_job("job-1")

        scheduler_service._scheduler.remove_job.assert_called_once_with("job-1")
        mark_run.assert_called_once()
        update_job.assert_called_once_with("job-1", enabled=False, next_run_at=None)
        create_notification.assert_awaited_once_with(job, "conv-1")
        deliver_to_platform.assert_awaited_once_with(job, "conv-1")
        assert scheduler_service._active_jobs == {}

    @pytest.mark.asyncio
    async def test_execute_job_creates_error_notification_on_failure(
        self, scheduler_service
    ):
        job = {
            "id": "job-1",
            "name": "Digest",
            "enabled": True,
            "is_one_shot": False,
            "timezone": "UTC",
            "cron_expression": "0 9 * * *",
        }

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch.object(
                scheduler_service,
                "_run_job_query",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(
                scheduler_service, "_create_error_notification", AsyncMock()
            ) as error_notification,
        ):
            await scheduler_service._execute_job("job-1")

        error_notification.assert_awaited_once_with(job, "boom")
        assert scheduler_service._active_jobs == {}

    @pytest.mark.asyncio
    async def test_run_job_now_returns_none_for_missing_job(self, scheduler_service):
        with patch(
            "source.services.scheduling.scheduler.db.get_scheduled_job",
            return_value=None,
        ):
            result = await scheduler_service.run_job_now("missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_run_job_query_routes_local_models_through_global_queue(
        self, scheduler_service
    ):
        session = SimpleNamespace(
            state=SimpleNamespace(chat_history=["old"], conversation_id="stale"),
            queue=SimpleNamespace(),
        )
        job = {
            "id": "job-1",
            "name": "Digest",
            "instruction": "Summarize",
            "model": "qwen3:local",
        }

        async def fake_queue_run(tab_id, fn):
            assert tab_id == "scheduled_job_job-1"
            return await fn()

        with (
            patch(
                "source.services.chat.tab_manager_instance.tab_manager",
                SimpleNamespace(get_or_create=MagicMock(return_value=session)),
            ),
            patch(
                "source.services.chat.ollama_global_queue.ollama_global_queue.run",
                new=AsyncMock(side_effect=fake_queue_run),
            ) as queue_run,
            patch("source.llm.core.router.is_local_ollama_model", return_value=True),
            patch(
                "source.services.chat.conversations.ConversationService.submit_query",
                new=AsyncMock(return_value="conv-final"),
            ) as submit_query,
            patch(
                "source.services.scheduling.scheduler.db.start_job_conversation",
                return_value="conv-created",
            ),
        ):
            result = await scheduler_service._run_job_query(job)

        assert result == "conv-final"
        assert session.state.chat_history == []
        assert session.state.conversation_id == "conv-created"
        queue_run.assert_awaited_once()
        submit_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_job_query_bypasses_queue_for_non_local_models(
        self, scheduler_service
    ):
        session = SimpleNamespace(
            state=SimpleNamespace(chat_history=["old"], conversation_id="stale"),
            queue=SimpleNamespace(),
        )
        job = {
            "id": "job-1",
            "name": "Digest",
            "instruction": "Summarize",
            "model": "openai/gpt-4o",
        }

        with (
            patch(
                "source.services.chat.tab_manager_instance.tab_manager",
                SimpleNamespace(get_or_create=MagicMock(return_value=session)),
            ),
            patch(
                "source.services.chat.ollama_global_queue.ollama_global_queue.run",
                new=AsyncMock(),
            ) as queue_run,
            patch("source.llm.core.router.is_local_ollama_model", return_value=False),
            patch(
                "source.services.chat.conversations.ConversationService.submit_query",
                new=AsyncMock(return_value="conv-final"),
            ) as submit_query,
            patch(
                "source.services.scheduling.scheduler.db.start_job_conversation",
                return_value="conv-created",
            ),
        ):
            result = await scheduler_service._run_job_query(job)

        assert result == "conv-final"
        queue_run.assert_not_called()
        submit_query.assert_awaited_once()


class TestSchedulerNotificationsAndDelivery:
    @pytest.mark.asyncio
    async def test_create_job_notification_truncates_preview(self, scheduler_service):
        job = {"id": "job-1", "name": "Digest"}
        messages = [{"role": "assistant", "content": "x" * 200}]
        notification = {"id": "note-1"}

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_full_conversation",
                return_value=messages,
            ),
            patch(
                "source.services.scheduling.scheduler.db.create_notification",
                return_value=notification,
            ) as create_notification,
            patch(
                "source.services.scheduling.scheduler.broadcast_message",
                new_callable=AsyncMock,
            ) as broadcast_message,
        ):
            await scheduler_service._create_job_notification(job, "conv-1")

        preview = create_notification.call_args.kwargs["body"]
        assert len(preview) == 153
        assert preview.endswith("...")
        broadcast_message.assert_awaited_once_with("notification_added", notification)

    @pytest.mark.asyncio
    async def test_deliver_to_platform_uses_global_defaults_and_truncates(
        self, scheduler_service
    ):
        job = {
            "id": "job-1",
            "name": "Digest",
            "delivery_platform": None,
            "delivery_sender_id": None,
        }
        messages = [{"role": "assistant", "content": "y" * 600}]

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_setting",
                side_effect=["telegram", "user-1"],
            ),
            patch(
                "source.services.scheduling.scheduler.db.get_full_conversation",
                return_value=messages,
            ),
            patch(
                "source.services.integrations.mobile_channel.mobile_channel_service.relay_response",
                new=AsyncMock(),
            ) as relay_response,
        ):
            await scheduler_service._deliver_to_platform(job, "conv-1")

        relay_kwargs = relay_response.await_args.kwargs
        assert relay_kwargs["platform"] == "telegram"
        assert relay_kwargs["sender_id"] == "user-1"
        assert relay_kwargs["thread_id"] == "user-1"
        assert relay_kwargs["response_text"].startswith("Digest:\n\n")
        assert relay_kwargs["response_text"].endswith(
            "Open Xpdite for the full result."
        )

    @pytest.mark.asyncio
    async def test_run_job_now_updates_metadata_and_creates_notifications(
        self, scheduler_service
    ):
        job = {
            "id": "job-1",
            "name": "Digest",
            "next_run_at": 456.0,
        }

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch.object(
                scheduler_service,
                "_run_job_query",
                AsyncMock(return_value="conv-1"),
            ),
            patch(
                "source.services.scheduling.scheduler.db.mark_job_run"
            ) as mark_run,
            patch.object(
                scheduler_service, "_create_job_notification", AsyncMock()
            ) as create_notification,
            patch.object(
                scheduler_service, "_deliver_to_platform", AsyncMock()
            ) as deliver_to_platform,
        ):
            result = await scheduler_service.run_job_now("job-1")

        assert result == "conv-1"
        mark_run.assert_called_once()
        create_notification.assert_awaited_once_with(job, "conv-1")
        deliver_to_platform.assert_awaited_once_with(job, "conv-1")


class TestSchedulerReschedule:
    @pytest.mark.asyncio
    async def test_reschedule_job_recomputes_next_run_and_reschedules_enabled_job(
        self, scheduler_service
    ):
        scheduler_service._scheduler = MagicMock()
        scheduler_service._running = True
        job = {
            "id": "job-1",
            "name": "Digest",
            "enabled": True,
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        }
        next_fire = datetime(2026, 4, 18, 9, 0, tzinfo=timezone.utc)
        trigger = MagicMock()
        trigger.get_next_fire_time.return_value = next_fire
        updated_job = {**job, "next_run_at": next_fire.timestamp()}

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch(
                "source.services.scheduling.scheduler.CronTrigger.from_crontab",
                return_value=trigger,
            ),
            patch(
                "source.services.scheduling.scheduler.db.update_scheduled_job",
                return_value=updated_job,
            ) as update_job,
            patch.object(scheduler_service, "_schedule_job") as schedule_job,
        ):
            result = await scheduler_service._reschedule_job("job-1")

        scheduler_service._scheduler.remove_job.assert_called_once_with("job-1")
        update_job.assert_called_once_with("job-1", next_run_at=next_fire.timestamp())
        schedule_job.assert_called_once_with(updated_job)
        assert result == updated_job

    @pytest.mark.asyncio
    async def test_reschedule_job_clears_next_run_for_disabled_job(self, scheduler_service):
        scheduler_service._scheduler = MagicMock()
        job = {
            "id": "job-1",
            "name": "Digest",
            "enabled": False,
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        }
        updated_job = {**job, "next_run_at": None}

        with (
            patch(
                "source.services.scheduling.scheduler.db.get_scheduled_job",
                return_value=job,
            ),
            patch(
                "source.services.scheduling.scheduler.db.update_scheduled_job",
                return_value=updated_job,
            ) as update_job,
            patch.object(scheduler_service, "_schedule_job") as schedule_job,
        ):
            result = await scheduler_service._reschedule_job("job-1")

        scheduler_service._scheduler.remove_job.assert_called_once_with("job-1")
        update_job.assert_called_once_with("job-1", next_run_at=None)
        schedule_job.assert_not_called()
        assert result == updated_job

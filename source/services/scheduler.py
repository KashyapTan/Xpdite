"""
Scheduled Jobs Service.

Manages recurring and one-shot scheduled tasks that execute AI requests
at specified times. Uses APScheduler for cron parsing and job management.

Jobs run identically to normal chat requests - full MCP tool access,
same execution path through ConversationService.submit_query().
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..core.connection import (
    broadcast_message,
    set_current_tab_id,
    reset_current_tab_id,
)
from ..core.request_context import (
    RequestContext,
    set_current_request,
    set_current_model,
)
from ..database import db

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled job lifecycle and execution."""

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False
        # Track active job executions for graceful shutdown
        self._active_jobs: Dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the scheduler and load all enabled jobs from the database."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._scheduler = AsyncIOScheduler(timezone="UTC")

        # Load all enabled jobs from the database
        jobs = db.list_scheduled_jobs(enabled_only=True)
        for job in jobs:
            self._schedule_job(job)
            logger.info(f"Loaded scheduled job: {job['name']} ({job['id']})")

        self._scheduler.start()
        self._running = True
        logger.info(f"Scheduler started with {len(jobs)} enabled job(s)")

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self._running or not self._scheduler:
            return

        # Cancel all active job executions
        for job_id, task in list(self._active_jobs.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Scheduler stopped")

    def _schedule_job(self, job: Dict[str, Any]) -> None:
        """Register a job with APScheduler."""
        if not self._scheduler:
            return

        job_id = job["id"]
        cron_expr = job["cron_expression"]
        timezone = job["timezone"]

        try:
            # Parse the cron expression with the job's timezone
            tz = ZoneInfo(timezone)
            trigger = CronTrigger.from_crontab(cron_expr, timezone=tz)

            self._scheduler.add_job(
                self._execute_job,
                trigger=trigger,
                args=[job_id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=60,  # Allow 60 seconds late execution
            )

            # Update next_run_at in the database
            next_run = trigger.get_next_fire_time(None, datetime.now(tz))
            if next_run:
                db.update_scheduled_job(job_id, next_run_at=next_run.timestamp())

        except Exception as e:
            logger.error(f"Failed to schedule job {job_id}: {e}")

    async def _execute_job(self, job_id: str) -> None:
        """Execute a scheduled job."""
        job = db.get_scheduled_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found in database")
            return

        if not job["enabled"]:
            logger.info(f"Skipping disabled job: {job['name']}")
            return

        logger.info(f"Executing scheduled job: {job['name']} ({job_id})")

        # Track active execution
        execution_task = asyncio.current_task()
        if execution_task:
            self._active_jobs[job_id] = execution_task

        try:
            # Execute the job's instruction as an AI request
            conversation_id = await self._run_job_query(job)

            # Calculate next run time for recurring jobs
            next_run_at: Optional[float] = None
            if not job["is_one_shot"] and self._scheduler:
                try:
                    tz = ZoneInfo(job["timezone"])
                    trigger = CronTrigger.from_crontab(
                        job["cron_expression"], timezone=tz
                    )
                    next_fire = trigger.get_next_fire_time(None, datetime.now(tz))
                    if next_fire:
                        next_run_at = next_fire.timestamp()
                except Exception as e:
                    logger.error(f"Failed to calculate next run time for {job_id}: {e}")

            # Update job metadata
            now = time.time()
            updates: Dict[str, Any] = {}

            if job["is_one_shot"]:
                # Disable one-shot jobs after execution
                updates["enabled"] = False
                updates["next_run_at"] = None
                # Remove from scheduler
                if self._scheduler:
                    try:
                        self._scheduler.remove_job(job_id)
                    except Exception:
                        pass

            db.mark_job_run(job_id, last_run_at=now, next_run_at=next_run_at)
            if updates:
                db.update_scheduled_job(job_id, **updates)

            # Create notification
            if conversation_id:
                await self._create_job_notification(job, conversation_id)

            # Platform delivery
            if conversation_id:
                await self._deliver_to_platform(job, conversation_id)

            logger.info(f"Completed scheduled job: {job['name']}")

        except asyncio.CancelledError:
            logger.info(f"Job {job['name']} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Job {job['name']} failed: {e}")
            # Create error notification
            await self._create_error_notification(job, str(e))
        finally:
            self._active_jobs.pop(job_id, None)

    async def _run_job_query(self, job: Dict[str, Any]) -> Optional[str]:
        """Run the job's instruction through the AI system."""
        # Import here to avoid circular imports
        from .conversations import ConversationService
        from .tab_manager_instance import tab_manager
        from .ollama_global_queue import ollama_global_queue
        from ..llm.router import is_local_ollama_model

        # Use a dedicated tab for scheduled job execution
        tab_id = f"scheduled_job_{job['id']}"
        session = tab_manager.get_or_create(tab_id)

        # Clear any previous state for fresh execution
        session.state.chat_history = []
        session.state.conversation_id = None

        model = job["model"]
        instruction = job["instruction"]

        async def _do_submit() -> Optional[str]:
            token = set_current_tab_id(tab_id)
            try:
                # Create a conversation tagged with the job ID and name
                conversation_id = db.start_job_conversation(
                    title=f"[Job] {job['name']}",
                    job_id=job["id"],
                    job_name=job["name"],
                )
                session.state.conversation_id = conversation_id

                # Set up request context
                ctx = RequestContext()
                set_current_request(ctx)
                set_current_model(model)

                try:
                    # Execute the query
                    result_conv_id = await ConversationService.submit_query(
                        user_query=instruction,
                        capture_mode="none",
                        tab_state=session.state,
                        queue=session.queue,
                        model=model,
                        action="submit",
                    )
                    return result_conv_id
                finally:
                    ctx.mark_done()
                    set_current_request(None)
                    set_current_model(None)
            finally:
                reset_current_tab_id(token)

        # Route local Ollama models through the global queue
        if model and is_local_ollama_model(model):
            return await ollama_global_queue.run(tab_id, _do_submit)
        else:
            return await _do_submit()

    async def _create_job_notification(
        self, job: Dict[str, Any], conversation_id: str
    ) -> None:
        """Create a notification for job completion."""
        # Get the conversation to extract a preview
        messages = db.get_full_conversation(conversation_id)
        assistant_msg = next(
            (m for m in reversed(messages) if m["role"] == "assistant"), None
        )

        preview = ""
        if assistant_msg and assistant_msg.get("content"):
            content = assistant_msg["content"]
            preview = content[:150] + "..." if len(content) > 150 else content

        notification = db.create_notification(
            notification_type="job_complete",
            title=job["name"],
            body=preview,
            payload={
                "job_id": job["id"],
                "conversation_id": conversation_id,
            },
        )

        # Broadcast to all connected clients
        await broadcast_message("notification_added", notification)

    async def _create_error_notification(self, job: Dict[str, Any], error: str) -> None:
        """Create a notification for job failure."""
        notification = db.create_notification(
            notification_type="job_error",
            title=f"{job['name']} failed",
            body=error[:150] if len(error) > 150 else error,
            payload={"job_id": job["id"]},
        )
        await broadcast_message("notification_added", notification)

    async def _deliver_to_platform(
        self, job: Dict[str, Any], conversation_id: str
    ) -> None:
        """Deliver job result to a messaging platform if configured."""
        # Determine delivery target
        platform = job.get("delivery_platform")
        sender_id = job.get("delivery_sender_id")

        # Check for global default if not set on job
        if not platform or not sender_id:
            global_platform = db.get_setting("scheduled_jobs_default_platform")
            global_sender_id = db.get_setting("scheduled_jobs_default_sender_id")
            if global_platform and global_sender_id:
                platform = platform or global_platform
                sender_id = sender_id or global_sender_id

        if not platform or not sender_id:
            return  # No delivery target configured

        try:
            from .mobile_channel import mobile_channel_service

            # Get the conversation content
            messages = db.get_full_conversation(conversation_id)
            assistant_msg = next(
                (m for m in reversed(messages) if m["role"] == "assistant"), None
            )

            if not assistant_msg or not assistant_msg.get("content"):
                return

            content = assistant_msg["content"]

            # Format message for platform delivery
            # Truncate to 500 chars with note if too long
            max_chars = 500
            if len(content) > max_chars:
                formatted_content = (
                    f"{job['name']}:\n\n"
                    f"{content[:max_chars]}...\n\n"
                    "Open Xpdite for the full result."
                )
            else:
                formatted_content = f"{job['name']}:\n\n{content}"

            # Send to the platform
            await mobile_channel_service.relay_response(
                platform=platform,
                sender_id=sender_id,
                response_text=formatted_content,
                thread_id=sender_id,  # Use sender_id as thread for direct message
            )
            logger.info(f"Delivered job result to {platform}:{sender_id}")

        except Exception as e:
            # Platform delivery is best-effort - log but don't fail
            logger.warning(f"Failed to deliver job result to platform: {e}")

    # ─── Public API for job management ───────────────────────────────

    async def create_job(
        self,
        name: str,
        cron_expression: str,
        instruction: str,
        timezone: str,
        model: Optional[str] = None,
        delivery_platform: Optional[str] = None,
        delivery_sender_id: Optional[str] = None,
        is_one_shot: bool = False,
    ) -> Dict[str, Any]:
        """Create and schedule a new job."""
        # Calculate initial next_run_at
        try:
            tz = ZoneInfo(timezone)
            trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
            next_fire = trigger.get_next_fire_time(None, datetime.now(tz))
            next_run_at = next_fire.timestamp() if next_fire else None
        except Exception as e:
            raise ValueError(f"Invalid cron expression: {e}")

        job = db.create_scheduled_job(
            name=name,
            cron_expression=cron_expression,
            instruction=instruction,
            timezone=timezone,
            model=model,
            delivery_platform=delivery_platform,
            delivery_sender_id=delivery_sender_id,
            is_one_shot=is_one_shot,
            next_run_at=next_run_at,
        )

        # Schedule with APScheduler
        if self._running:
            self._schedule_job(job)

        logger.info(f"Created scheduled job: {name} ({job['id']})")
        return job

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job and remove from scheduler."""
        job = db.get_scheduled_job(job_id)
        if not job:
            return False

        # Remove from scheduler
        if self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass  # Job may not be in scheduler

        # Cancel if currently executing
        if job_id in self._active_jobs:
            self._active_jobs[job_id].cancel()

        db.delete_scheduled_job(job_id)
        logger.info(f"Deleted scheduled job: {job['name']} ({job_id})")
        return True

    async def pause_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Pause a job (disable without deleting)."""
        job = db.get_scheduled_job(job_id)
        if not job:
            return None

        # Remove from scheduler
        if self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

        updated = db.update_scheduled_job(job_id, enabled=False)
        logger.info(f"Paused scheduled job: {job['name']}")
        return updated

    async def resume_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Resume a paused job."""
        job = db.get_scheduled_job(job_id)
        if not job:
            return None

        # Update database first
        updated = db.update_scheduled_job(job_id, enabled=True)
        if not updated:
            return None

        # Re-schedule with APScheduler
        if self._running:
            self._schedule_job(updated)

        logger.info(f"Resumed scheduled job: {job['name']}")
        return updated

    async def run_job_now(self, job_id: str) -> Optional[str]:
        """Manually trigger a job to run immediately.

        Returns the conversation_id if successful.
        """
        job = db.get_scheduled_job(job_id)
        if not job:
            return None

        logger.info(f"Manually triggering job: {job['name']}")

        # Execute in a background task
        conversation_id = await self._run_job_query(job)

        # Update run metadata but don't change next_run_at for recurring jobs
        db.mark_job_run(job_id, last_run_at=time.time(), next_run_at=job["next_run_at"])

        # Create notification
        if conversation_id:
            await self._create_job_notification(job, conversation_id)
            await self._deliver_to_platform(job, conversation_id)

        return conversation_id

    def list_jobs(self, enabled_only: bool = False) -> list[Dict[str, Any]]:
        """List all scheduled jobs."""
        return db.list_scheduled_jobs(enabled_only=enabled_only)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        return db.get_scheduled_job(job_id)


# Global singleton instance
scheduler_service = SchedulerService()

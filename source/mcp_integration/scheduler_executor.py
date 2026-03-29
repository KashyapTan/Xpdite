"""
Scheduler inline tool executor.

Handles execution of scheduler tools (create_job, list_jobs, etc.)
directly in the Python backend without going through MCP subprocess.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from ..core.request_context import get_current_model

logger = logging.getLogger(__name__)

# Tools handled by this executor
SCHEDULER_TOOLS = {
    "create_job",
    "list_jobs",
    "delete_job",
    "pause_job",
    "resume_job",
    "run_job_now",
}


def is_scheduler_tool(fn_name: str, server_name: str) -> bool:
    """Check if a tool call should be handled by the scheduler executor."""
    return server_name == "scheduler" and fn_name in SCHEDULER_TOOLS


async def execute_scheduler_tool(
    fn_name: str, fn_args: Dict[str, Any], server_name: str
) -> str:
    """Execute a scheduler tool and return the result as a string."""
    if fn_name == "create_job":
        return await _handle_create_job(fn_args)
    elif fn_name == "list_jobs":
        return await _handle_list_jobs(fn_args)
    elif fn_name == "delete_job":
        return await _handle_delete_job(fn_args)
    elif fn_name == "pause_job":
        return await _handle_pause_job(fn_args)
    elif fn_name == "resume_job":
        return await _handle_resume_job(fn_args)
    elif fn_name == "run_job_now":
        return await _handle_run_job_now(fn_args)
    else:
        return f"Unknown scheduler tool: {fn_name}"


async def _handle_create_job(args: Dict[str, Any]) -> str:
    """Handle the create_job tool."""
    from ..services.scheduler import scheduler_service

    name = args.get("name")
    cron_expression = args.get("cron_expression")
    instruction = args.get("instruction")
    timezone = args.get("timezone")
    model = args.get("model") or get_current_model()
    delivery_platform = args.get("delivery_platform")
    delivery_sender_id = args.get("delivery_sender_id")
    is_one_shot = args.get("is_one_shot", False)

    # Validate required fields
    if not name:
        return "Error: 'name' is required"
    if not cron_expression:
        return "Error: 'cron_expression' is required"
    if not instruction:
        return "Error: 'instruction' is required"
    if not timezone:
        return "Error: 'timezone' is required"

    # Validate timezone
    try:
        ZoneInfo(timezone)
    except Exception:
        return f"Error: Invalid timezone '{timezone}'. Use IANA format (e.g., 'America/New_York')."

    try:
        job = await scheduler_service.create_job(
            name=name,
            cron_expression=cron_expression,
            instruction=instruction,
            timezone=timezone,
            model=model,
            delivery_platform=delivery_platform,
            delivery_sender_id=delivery_sender_id,
            is_one_shot=is_one_shot,
        )

        # Format next run time in the job's timezone
        next_run_str = "Not scheduled"
        if job.get("next_run_at"):
            tz = ZoneInfo(timezone)
            next_run = datetime.fromtimestamp(job["next_run_at"], tz)
            next_run_str = next_run.strftime("%Y-%m-%d %H:%M %Z")

        return (
            f"Successfully created scheduled job:\n"
            f"• Name: {job['name']}\n"
            f"• ID: {job['id']}\n"
            f"• Schedule: {cron_expression}\n"
            f"• Timezone: {timezone}\n"
            f"• Next run: {next_run_str}\n"
            f"• Model: {model or 'default'}\n"
            f"• One-shot: {'Yes' if is_one_shot else 'No'}"
        )
    except ValueError as e:
        return f"Error creating job: {e}"
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        return f"Error: Failed to create job - {e}"


async def _handle_list_jobs(args: Dict[str, Any]) -> str:
    """Handle the list_jobs tool."""
    from ..services.scheduler import scheduler_service

    jobs = scheduler_service.list_jobs()

    if not jobs:
        return "No scheduled jobs configured. Create one by describing when you want a task to run."

    lines = ["Scheduled Jobs:", ""]

    for job in jobs:
        status = "Enabled" if job["enabled"] else "Paused"

        # Format times in job's timezone
        tz = ZoneInfo(job["timezone"])

        next_run = "N/A"
        if job.get("next_run_at"):
            dt = datetime.fromtimestamp(job["next_run_at"], tz)
            next_run = dt.strftime("%Y-%m-%d %H:%M %Z")

        last_run = "Never"
        if job.get("last_run_at"):
            dt = datetime.fromtimestamp(job["last_run_at"], tz)
            last_run = dt.strftime("%Y-%m-%d %H:%M %Z")

        lines.append(f"• {job['name']} [{status}]")
        lines.append(f"  ID: {job['id']}")
        lines.append(f"  Schedule: {job['cron_expression']} ({job['timezone']})")
        lines.append(f"  Next run: {next_run}")
        lines.append(f"  Last run: {last_run}")
        lines.append(f"  Run count: {job['run_count']}")
        if job.get("is_one_shot"):
            lines.append("  Type: One-shot")
        lines.append("")

    return "\n".join(lines)


async def _handle_delete_job(args: Dict[str, Any]) -> str:
    """Handle the delete_job tool."""
    from ..services.scheduler import scheduler_service

    job_id = args.get("job_id")
    if not job_id:
        return "Error: 'job_id' is required"

    # Get job name before deletion
    job = scheduler_service.get_job(job_id)
    if not job:
        return f"Error: Job with ID '{job_id}' not found"

    success = await scheduler_service.delete_job(job_id)
    if success:
        return f"Successfully deleted job: {job['name']}"
    else:
        return f"Error: Failed to delete job '{job_id}'"


async def _handle_pause_job(args: Dict[str, Any]) -> str:
    """Handle the pause_job tool."""
    from ..services.scheduler import scheduler_service

    job_id = args.get("job_id")
    if not job_id:
        return "Error: 'job_id' is required"

    job = await scheduler_service.pause_job(job_id)
    if not job:
        return f"Error: Job with ID '{job_id}' not found"

    return f"Successfully paused job: {job['name']}"


async def _handle_resume_job(args: Dict[str, Any]) -> str:
    """Handle the resume_job tool."""
    from ..services.scheduler import scheduler_service

    job_id = args.get("job_id")
    if not job_id:
        return "Error: 'job_id' is required"

    job = await scheduler_service.resume_job(job_id)
    if not job:
        return f"Error: Job with ID '{job_id}' not found"

    # Format next run time
    next_run = "Not scheduled"
    if job.get("next_run_at"):
        tz = ZoneInfo(job["timezone"])
        dt = datetime.fromtimestamp(job["next_run_at"], tz)
        next_run = dt.strftime("%Y-%m-%d %H:%M %Z")

    return f"Successfully resumed job: {job['name']}\nNext run: {next_run}"


async def _handle_run_job_now(args: Dict[str, Any]) -> str:
    """Handle the run_job_now tool."""
    from ..services.scheduler import scheduler_service

    job_id = args.get("job_id")
    if not job_id:
        return "Error: 'job_id' is required"

    job = scheduler_service.get_job(job_id)
    if not job:
        return f"Error: Job with ID '{job_id}' not found"

    try:
        conversation_id = await scheduler_service.run_job_now(job_id)
        if conversation_id:
            return (
                f"Successfully triggered job: {job['name']}\n"
                f"Conversation ID: {conversation_id}\n"
                f"The result will appear in notifications and the Scheduled Jobs results page."
            )
        else:
            return f"Job '{job['name']}' executed but did not produce a conversation."
    except Exception as e:
        logger.error(f"Failed to run job now: {e}")
        return f"Error running job: {e}"

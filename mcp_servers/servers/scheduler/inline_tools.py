"""
Scheduler inline tool definitions.

These tools allow the LLM to create and manage scheduled jobs that
execute AI requests at specified times.
"""

from typing import Any

from mcp_servers.servers.description_format import build_inline_tool_definition

CREATE_JOB_DESCRIPTION = """
Purpose: Create a new scheduled job that will execute an AI request at specified times.
Use when: User asks to schedule a recurring or one-time task (e.g., "summarize my emails every morning at 9am").
Inputs: Job name, cron expression, self-contained instruction prompt, timezone, optional model, optional delivery target.
Returns: The created job details including ID and next run time.
Notes: 
- The instruction must be completely self-contained - it will run with zero context later.
- Always capture the user's timezone from the system at creation time.
- The cron expression uses standard 5-field format: minute hour day_of_month month day_of_week.
- Examples: "0 9 * * *" (9am daily), "0 9 * * 1-5" (9am weekdays), "30 18 * * *" (6:30pm daily).
""".strip()

LIST_JOBS_DESCRIPTION = """
Purpose: List all scheduled jobs with their status and timing information.
Use when: User asks about their scheduled jobs, wants to see what's configured, or needs job IDs.
Inputs: None required.
Returns: List of all jobs with name, schedule, enabled status, next/last run times.
""".strip()

DELETE_JOB_DESCRIPTION = """
Purpose: Permanently delete a scheduled job.
Use when: User wants to remove a scheduled job entirely.
Inputs: Job ID to delete.
Returns: Confirmation of deletion.
""".strip()

PAUSE_JOB_DESCRIPTION = """
Purpose: Temporarily disable a scheduled job without deleting it.
Use when: User wants to stop a job temporarily but keep it for later.
Inputs: Job ID to pause.
Returns: Updated job status.
""".strip()

RESUME_JOB_DESCRIPTION = """
Purpose: Re-enable a paused scheduled job.
Use when: User wants to restart a previously paused job.
Inputs: Job ID to resume.
Returns: Updated job status with next run time.
""".strip()

RUN_JOB_NOW_DESCRIPTION = """
Purpose: Manually trigger a scheduled job to run immediately.
Use when: User wants to test a job or run it outside its normal schedule.
Inputs: Job ID to run.
Returns: The conversation ID of the execution result.
""".strip()


SCHEDULER_INLINE_TOOLS: list[dict[str, Any]] = [
    build_inline_tool_definition(
        "create_job",
        CREATE_JOB_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the job (e.g., 'Morning Email Summary')",
                },
                "cron_expression": {
                    "type": "string",
                    "description": "Standard 5-field cron expression (minute hour day month weekday)",
                },
                "instruction": {
                    "type": "string",
                    "description": "Self-contained instruction that will be executed as an AI request. Must work with zero context.",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone for scheduling (e.g., 'America/New_York', 'Europe/London')",
                },
                "model": {
                    "type": "string",
                    "description": "LLM model to use for execution. Defaults to current model if not specified.",
                },
                "delivery_platform": {
                    "type": "string",
                    "enum": ["whatsapp", "telegram", "discord"],
                    "description": "Platform to deliver results to (optional)",
                },
                "delivery_sender_id": {
                    "type": "string",
                    "description": "Sender ID on the delivery platform (optional)",
                },
                "is_one_shot": {
                    "type": "boolean",
                    "description": "If true, job runs once and is disabled. Default is false (recurring).",
                    "default": False,
                },
            },
            "required": ["name", "cron_expression", "instruction", "timezone"],
        },
    ),
    build_inline_tool_definition(
        "list_jobs",
        LIST_JOBS_DESCRIPTION,
        {
            "type": "object",
            "properties": {},
        },
    ),
    build_inline_tool_definition(
        "delete_job",
        DELETE_JOB_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID of the job to delete",
                },
            },
            "required": ["job_id"],
        },
    ),
    build_inline_tool_definition(
        "pause_job",
        PAUSE_JOB_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID of the job to pause",
                },
            },
            "required": ["job_id"],
        },
    ),
    build_inline_tool_definition(
        "resume_job",
        RESUME_JOB_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID of the job to resume",
                },
            },
            "required": ["job_id"],
        },
    ),
    build_inline_tool_definition(
        "run_job_now",
        RUN_JOB_NOW_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID of the job to run immediately",
                },
            },
            "required": ["job_id"],
        },
    ),
]

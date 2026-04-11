# Scheduled Jobs

Scheduled jobs let Xpdite execute AI tasks automatically on cron schedules or as one-shot runs.

## Execution Model

- Scheduler engine uses APScheduler (`AsyncIOScheduler`).
- Jobs are persisted in SQLite (`scheduled_jobs`).
- On trigger, job runs through normal conversation pipeline in isolated job tab context.

## Job Fields

- `name`
- `cron_expression`
- `instruction`
- `timezone`
- `model` (optional)
- `delivery_platform` (optional)
- `delivery_sender_id` (optional)
- `enabled`
- `is_one_shot`

## Lifecycle

1. Job created and scheduled.
2. Scheduler fires based on cron + timezone.
3. Instruction executes as fresh request.
4. Run metadata and next-run timestamps update.
5. One-shot jobs disable after first successful execution.
6. Notifications and optional mobile delivery are emitted.

## API

- `GET /api/scheduled-jobs`
- `GET /api/scheduled-jobs/{job_id}`
- `POST /api/scheduled-jobs`
- `PUT /api/scheduled-jobs/{job_id}`
- `DELETE /api/scheduled-jobs/{job_id}`
- `POST /api/scheduled-jobs/{job_id}/pause`
- `POST /api/scheduled-jobs/{job_id}/resume`
- `POST /api/scheduled-jobs/{job_id}/run-now`
- `GET /api/scheduled-jobs/conversations`
- `GET /api/scheduled-jobs/{job_id}/conversations`

## Delivery Behavior

- If delivery target is configured, final output is relayed to mobile channel integration as best effort.

## Related Docs

- `docs/notifications.md`
- `docs/mobile-bridge.md`
- `docs/api-reference.md`

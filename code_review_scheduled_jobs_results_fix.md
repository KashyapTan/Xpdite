# Code Review: Scheduled Jobs Results Not Showing

## Scope
- `source/api/http.py`
- `src/ui/pages/ScheduledJobsResults.tsx`
- `src/ui/components/NotificationBell.tsx`
- `src/ui/services/api.ts`
- `tests/test_http_api.py`

## Issues Found

1. **High — Static route was shadowed by dynamic route**
   - `GET /api/scheduled-jobs/conversations` could be matched by `GET /api/scheduled-jobs/{job_id}` when declared after the dynamic route.
   - Result: conversations endpoint did not return job conversations for the results page.

2. **High — Notification event name mismatch in frontend**
   - Frontend listened for `notification_created`, backend broadcasts `notification_added`.
   - Result: notification bell and downstream refresh behavior were inconsistent.

3. **High — Notification payload shape mismatch**
   - Frontend treated `notification.payload` as JSON string and called `JSON.parse`, while backend returns object/null.
   - Result: navigation from notifications could silently fail.

4. **Medium — Dismiss event content key mismatch**
   - Frontend read `message.data`, backend sends websocket payload in `message.content`.
   - Result: dismiss updates from websocket could be ignored.

## Fixes Applied

1. **Route precedence fix**
   - Moved static route declaration before dynamic route:
     - `@router.get("/scheduled-jobs/conversations")`
     - then `@router.get("/scheduled-jobs/{job_id}")`
   - File: `source/api/http.py`

2. **Realtime notification event fix**
   - Updated listener to `notification_added`.
   - File: `src/ui/components/NotificationBell.tsx`

3. **Payload typing and handling fix**
   - Updated notification payload type to `Record<string, unknown> | null`.
   - Removed `JSON.parse` and used payload object directly.
   - Files:
     - `src/ui/components/NotificationBell.tsx`
     - `src/ui/services/api.ts`

4. **Dismiss websocket payload key fix**
   - Read dismissal ID from `message.content`.
   - File: `src/ui/components/NotificationBell.tsx`

5. **Scheduled results realtime refresh improvement**
   - `ScheduledJobsResults` now refreshes on `notification_added` when type is `job_complete` or `job_error`.
   - File: `src/ui/pages/ScheduledJobsResults.tsx`

6. **Regression test added**
   - Added test to verify `/api/scheduled-jobs/conversations` returns job conversations payload.
   - File: `tests/test_http_api.py`

## Verification Run

- `bun run lint` (pass)
- `bun run test:frontend` (pass)
- `uv run python -m pytest tests/test_http_api.py -k scheduled_job_conversations -v` (pass)
- Runtime API sanity check via FastAPI `TestClient`:
  - `GET /api/scheduled-jobs/conversations` returned `200` and non-empty conversations.

## Final Verdict

**Ready** for this bugfix scope.
The root-cause route shadowing and related frontend event/data-shape mismatches were fixed and validated.

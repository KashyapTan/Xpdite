# Code Review — terminal service test coverage

Date: 2026-03-20
Scope: `tests/test_terminal.py`

## Stage 1 — Parallel Focused Reviewers

### Reviewer A — Correctness & Logic
- Found weak assertion in `test_get_recent_output` (`len(lines) <= 2`) that could pass on incorrect behavior.
- Found flaky timing pattern in `test_duration_ms` using real `time.sleep`.

### Reviewer B — Security & Resilience
- Found async-mock assertion quality issue (`assert_called_once` used on awaited async mocks).
- Flagged timeout tests that globally forced timeout behavior and could hide cleanup behavior.
- Reiterated `time.sleep` flakiness risk.

### Reviewer C — Performance & Quality
- Reiterated timing flakiness and suggested deterministic clock mocking.
- Identified missing explicit `execute_command` success-path test (`exit_code == 0`).
- Noted minor maintainability opportunities (parametrize repetitive tests, reduce brittle exact-string assertions).

## Stage 3 — Judge Synthesis

Merged result before fixes:
- No Critical/High findings.
- Medium findings required action for test robustness and branch confidence.

## Stage 4 — Fixes Applied

1. Deterministic duration test
- Replaced real sleep in `test_duration_ms` with patched `time.time` values.

2. Stronger output slicing assertion
- Updated `test_get_recent_output` to assert exact expected trailing output (`"line2\nline3"`).

3. Async mock correctness checks
- Switched `broadcast_message` timeout-path tests to `assert_awaited_once` and awaited-args checks.

4. Added explicit success-path command execution test
- Added `test_successful_exit_zero_does_not_append_exit_code_suffix` covering normal exit path.

5. Timeout mock safety
- Added `_wait_for_timeout` helper to close passed awaitables before raising timeout, avoiding un-awaited coroutine warnings.

## Verification

- Targeted tests: `uv run python -m pytest tests/test_terminal.py -q` → **70 passed**.
- Full backend tests with coverage: `uv run --with pytest-cov python -m pytest tests/ -q --cov=source --cov-report=term --cov-report=json:backend-coverage.json` → **734 passed**.
- Lint/static:
  - `bun run lint` → no errors (warnings only from generated `coverage/` assets).
  - `uv run ruff check .` → all checks passed.

## Coverage impact

- `source/services/terminal.py` improved from **35%** baseline to **70%** after this pass.
- Backend total improved from **55%** baseline to **57%**.

## Final verdict

READY WITH CAVEATS

- The implemented findings are fixed and verified.
- Remaining gaps are in other high-ROI modules (`source/api/handlers.py`, `source/mcp_integration/handlers.py`, `source/services/meeting_recorder.py`, and frontend targets) and should be addressed in subsequent one-file passes.

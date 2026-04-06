# Code Review & Quality Assurance Guide

> **How this guide is used:** This guide is read by both the **main Claude agent** (to orchestrate the review pipeline) and by each **sub-agent reviewer** (to focus their individual pass). Each sub-agent receives the section relevant to its role. The judge agent receives everything.

---

## Overview — The Review Pipeline

Production-grade review uses four stages. Do not skip stages for non-trivial changes.

```
┌─────────────────────────────────────────────────────┐
│  STAGE 1 — Parallel Focused Reviewers (simultaneous) │
│  Reviewer A: Correctness & Logic                     │
│  Reviewer B: Security & Resilience                   │
│  Reviewer C: Performance & Quality                   │
└───────────────────┬─────────────────────────────────┘
                    │ (all three raw reports)
                    ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 2 — Best-of-N (optional, high-risk diffs)    │
│  Spawn 2 extra Reviewer A agents for correctness.   │
│  Best / most complete findings win.                  │
└───────────────────┬─────────────────────────────────┘
                    │ (all raw reports)
                    ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 3 — Judge Agent (de-dup + false-pos filter)  │
│  Merges, de-dupes, ranks, resolves contradictions,  │
│  filters false positives → Final Report              │
└───────────────────┬─────────────────────────────────┘
                    │ (final report)
                    ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 4 — Fix & Verify                             │
│  Fix Critical + High. Verify fixes with a final     │
│  lightweight sub-agent check.                        │
└─────────────────────────────────────────────────────┘
```

**When to run the full pipeline:** Any change that touches business logic, DB schema, auth, LLM integration, MCP, or WebSocket protocol. For trivial changes (renaming, comment edits, config values), a single quick pass is sufficient.

---

## Instructions for Reviewer A — Correctness & Logic

> **Your only job:** Find logic bugs, incorrect behavior, and async problems. Do not comment on style, performance, or security — those belong to other reviewers. Be ruthless about correctness.

### Phase 1 — Correctness Verification

- Re-read the original task or requirements. Does the code fulfill **every** stated requirement?
- Trace through the core logic manually for at least **two representative inputs** — one happy path, one edge case.
- Identify any **off-by-one errors**, incorrect conditionals, or logic inversions.
- Check all **return values** — are they the right type and shape? Are any accidentally `None`/`undefined`/`null`?
- Verify that **async/await** or **Promise chains** are handled correctly and that async errors are caught.
- Confirm that **recursion** has a valid base case and won't stack-overflow on realistic inputs.
- Check that **mutations** are intentional — no accidental in-place modification of inputs the caller still owns.
- Verify ContextVar usage: per-request state must use `set_current_request()` / `get_current_model()` — never read `app_state` directly from LLM/MCP layers.
- Verify WebSocket message types: any new type must be registered in `websocket.py`'s docstring and handled in `MessageHandler`.

**Self-prompt:** *"If I handed this function a completely unexpected input, what would break? What happens on the second call? The thousandth?"*

### Reviewer A Output Format

```
## Reviewer A — Correctness & Logic

### Findings
- [CRITICAL/HIGH/MEDIUM/LOW] <file>:<line> — <description of issue> — <suggested fix>

### Verdict
PASS / FAIL
```

---

## Instructions for Reviewer B — Security & Resilience

> **Your only job:** Find security vulnerabilities, missing error handling, and resource leaks. Do not comment on logic correctness, style, or performance.

### Phase 2 — Security Audit

#### Input & Data Handling
- [ ] All user-supplied input is **validated and sanitized** before use.
- [ ] No raw string interpolation into **SQL queries** — parameterized queries or ORM only.
- [ ] No raw string interpolation into **shell commands** — use subprocess with argument lists.
- [ ] **HTML/template output** is escaped to prevent XSS.
- [ ] File paths derived from user input are **canonicalized** and checked against a safe root.

#### Secrets & Credentials
- [ ] No API keys, passwords, tokens, or secrets are **hardcoded** in source.
- [ ] Secrets are read from **environment variables or a secrets manager** only.
- [ ] No sensitive data (passwords, PII, tokens) is written to **logs**.

#### Authentication & Authorization
- [ ] Every protected endpoint checks **authentication** before doing work.
- [ ] Authorization is enforced at the **data layer**, not just the UI layer.
- [ ] No **IDOR** vulnerabilities — users cannot access other users' resources by changing an ID.

#### Dependencies
- [ ] Any newly introduced third-party packages are **well-maintained and not deprecated**.
- [ ] No packages with known **critical CVEs** introduced.

**Self-prompt:** *"What's the worst thing a malicious user could make this code do?"*

### Phase 3 — Error Handling & Resilience

- [ ] All **I/O operations** (file, network, database) have try/catch or equivalent error handling.
- [ ] Errors are **logged with enough context** to debug (without leaking sensitive data).
- [ ] User-facing error messages are **generic** — internal details never exposed.
- [ ] Functions that can fail return a clear **error signal** rather than silently returning bad data.
- [ ] **Timeouts** are set on any network calls or external service interactions.
- [ ] Retry logic uses **exponential backoff** with a max-retry cap.
- [ ] Resources (file handles, DB connections, locks) released in **finally blocks** or context managers.
- [ ] Code handles **partial failure** gracefully in batch or multi-step operations.
- [ ] SQLite: `check_same_thread=False` is present; all connections use `with self._connect() as conn:`.
- [ ] Streaming loops: `is_current_request_cancelled()` is checked at each iteration.
- [ ] `broadcast_message()` is used instead of `manager.broadcast()` in all service code.

**Self-prompt:** *"What happens when the network drops mid-request? When the DB is locked? When the LLM times out?"*

### Reviewer B Output Format

```
## Reviewer B — Security & Resilience

### Findings
- [CRITICAL/HIGH/MEDIUM/LOW] <file>:<line> — <description of issue> — <suggested fix>

### Verdict
PASS / FAIL
```

---

## Instructions for Reviewer C — Performance & Quality

> **Your only job:** Find performance problems, dead code, complexity issues, naming problems, and missing tests. Do not comment on correctness or security.

### Phase 4 — Performance & Efficiency

#### Algorithmic Complexity
- [ ] Review all loops. Any **O(n²) or worse** patterns that could be flattened with a set/map lookup?
- [ ] Large collections being **copied unnecessarily**? Use views, generators, or iterators.
- [ ] **Redundant computations** inside loops that could be hoisted out?

#### Database & I/O
- [ ] Any **N+1 query patterns**? Batch or join where possible.
- [ ] Are queries hitting **indexed columns**? Flag full-table scans on large datasets.
- [ ] Is **caching** appropriate? Same expensive computation called repeatedly with same inputs?
- [ ] Are large payloads **streamed** rather than loaded entirely into memory?
- [ ] All CPU-heavy or blocking-IO work goes through `run_in_thread` — never blocking the uvicorn event loop directly.

#### Memory
- [ ] No unbounded data structures that grow indefinitely without eviction.
- [ ] Large objects released as soon as no longer needed.

**Self-prompt:** *"How does this behave with 10x, 100x the expected data volume?"*

### Phase 5 — Code Simplification

- Deduplicate any logic appearing more than once — extract into a shared function.
- Remove **dead code**: unused variables, unreachable branches, commented-out blocks.
- Replace verbose conditionals with clearer equivalents (early returns, guard clauses).
- Functions exceeding **~40 lines** — evaluate whether they should be split.
- Nesting deeper than **3 levels** — refactor with early returns or helper functions.
- Replace **magic numbers and strings** with named constants.
- Prefer **standard library functions** over hand-rolled equivalents.

### Phase 6 — Code Style & Consistency

- [ ] Formatting consistent with surrounding codebase (indentation, quotes, semicolons).
- [ ] Imports organized; no unused imports remain.
- [ ] Public functions and complex logic have **docstrings/comments** explaining *why*, not just *what*.
- [ ] Type hints present on all public function signatures (Python) / all props typed (TypeScript).
- [ ] No `TODO` or `FIXME` comments left without a tracked issue reference.
- [ ] Python: relative imports only inside `source/` (`from ..infrastructure.config import ...`).
- [ ] TypeScript: no `any` unless bridging untyped external API; prefer `unknown` + narrow.
- [ ] Variable and function names **describe intent** (`fetchUserById` not `doThing`).
- [ ] Booleans read as assertions: `isActive`, `hasPermission`, `canRetry`.

### Phase 7 — Testability & Observability

- [ ] Core logic is in **pure functions** easy to unit test in isolation.
- [ ] Side effects (I/O, randomness, time) are **injected or abstracted**.
- [ ] Key operations emit **structured logs** that would let an engineer diagnose issues in production.
- [ ] If tests were written: do they cover **happy path, edge cases, and failure modes**?
- [ ] If no tests were written: flag the **most critical functions** that should be unit tested.

**Self-prompt:** *"Would a developer unfamiliar with this codebase understand what each function does from its name and signature alone?"*

### Reviewer C Output Format

```
## Reviewer C — Performance & Quality

### Findings
- [CRITICAL/HIGH/MEDIUM/LOW] <file>:<line> — <description of issue> — <suggested fix>

### Verdict
PASS / FAIL
```

---

## Instructions for the Judge Agent

> **You receive:** All raw reports from Reviewer A, Reviewer B, Reviewer C (and any Best-of-N duplicates). **Your job:** Produce the single authoritative final report. You are the last line of defense.

### Judge Checklist

1. **Merge** all findings into one list. Group by file/area when it aids clarity.
2. **Rank** every finding: Critical → High → Medium → Low.
   - Critical: data loss, security breach, crash in production, incorrect output silently returned.
   - High: will cause bugs under realistic conditions; auth gaps; resource leaks.
   - Medium: correctness risk under edge cases; performance under load; style that impedes maintenance.
   - Low: cosmetic, minor naming, optional improvements.
3. **De-duplicate:** If N reviewers flagged the same issue, keep one entry and note `(flagged by N/3 reviewers — high confidence)`.
4. **Resolve contradictions:** If two reviewers disagree, investigate and decide. Document your reasoning.
5. **Filter false positives:** Mark and discard findings that flag intentional, correct behavior. Common false positives in this codebase:
   - `check_same_thread=False` on SQLite — this is required by our `DatabaseManager` pattern, not a bug.
   - `manager.broadcast()` called inside `broadcast_message()` itself — that's the one legitimate call site.
   - `any` type on external LLM/WS API boundaries — explicitly allowed by code style rules.
   - `ALTER TABLE ADD COLUMN` in a try/except block — this is the correct migration pattern.
6. **Assess test coverage:** Flag the top 3 functions that most need tests if they don't already have them.
7. **Produce the final report** below.

### Final Report Format

```
## Code Review — Final Report (Judge Synthesis)

### 🔴 Critical  (fix before merge — no exceptions)
- [file:line] — [issue] — [fix]

### 🟠 High  (fix before merge)
- [file:line] — [issue] — [fix]

### 🟡 Medium  (fix if quick; flag for human review if architectural)
- [file:line] — [issue] — [fix or discussion point]

### 🟢 Low  (optional improvements)
- [file:line] — [issue] — [suggestion]

### ✅ Passed (already correct — note anything that was reviewed and found clean)
- [area] — [what was checked and confirmed correct]

### 🚫 False Positives Discarded
- [finding] — [reason it is intentional/correct]

### 🔧 Changes Made
- [issue] → [what was changed and why]  (filled in after fixes are applied)

### ⚠️ Flagged for Human Review
- [issue] — [why this needs a human decision: business logic ambiguity, infra-level change, etc.]

### 📋 Test Cases to Add
- [function/scenario] — [what should be tested and why]
- [function/scenario] — [what should be tested and why]
- [function/scenario] — [what should be tested and why]

### Confidence Scores (from parallel runs)
| Finding | Flagged By | Confidence |
|---------|------------|------------|
| [issue] | A, B | High |
| [issue] | C only | Medium |

### Production Readiness Verdict
**READY** / **READY WITH CAVEATS** / **NOT READY**
Reason: [One sentence summary]
```

---

## Final Checklist (Judge confirms all before READY verdict)

| # | Check | Status |
|---|-------|--------|
| 1 | Fulfills all requirements | ☐ |
| 2 | No hardcoded secrets | ☐ |
| 3 | All inputs validated/sanitized | ☐ |
| 4 | All errors handled gracefully | ☐ |
| 5 | No obvious performance bottlenecks | ☐ |
| 6 | No dead or duplicate code | ☐ |
| 7 | Naming is clear and intentional | ☐ |
| 8 | Code is formatted and consistent | ☐ |
| 9 | Critical paths are observable (logging) | ☐ |
| 10 | Test coverage is adequate or gaps documented | ☐ |
| 11 | ContextVar isolation maintained (no app_state reads in LLM/MCP layers) | ☐ |
| 12 | WebSocket docstring updated for any new message types | ☐ |
| 13 | No `manager.broadcast()` calls in service code | ☐ |
| 14 | DB migrations use ALTER TABLE pattern, not CREATE TABLE modification | ☐ |
| 15 | No hardcoded ports — `find_available_port()` used | ☐ |

---

> **Reminder to all agents:** The goal is not to rewrite working code for the sake of it. Flag or fix only what meaningfully improves safety, correctness, performance, or maintainability. When in doubt about a refactor, the judge flags it for human review rather than changing it unilaterally.
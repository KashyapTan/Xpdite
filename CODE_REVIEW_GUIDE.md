# Code Review & Quality Assurance Guide
> **Instructions for Claude Opus 4.6:** After completing any coding task, use this document as a checklist to review, simplify, verify, and certify the code as production-ready. Work through each section systematically. Flag every issue found, fix it inline, and provide a final summary report.

---

## Phase 1 — Correctness Verification

Before anything else, confirm the code actually does what it was asked to do.

- Re-read the original task or requirements. Does the code fulfill **every** stated requirement?
- Trace through the core logic manually (or via mental simulation) for at least **two representative inputs** — one happy path, one edge case.
- Identify any **off-by-one errors**, incorrect conditionals, or logic inversions.
- Check all **return values** — are they the right type and shape? Are any accidentally `None`/`undefined`/`null`?
- Verify that **async/await** or **Promise chains** are handled correctly and that async errors are caught.
- Confirm that **recursion** has a valid base case and won't stack-overflow on realistic inputs.
- Check that **mutations** are intentional — no accidental in-place modification of inputs the caller still owns.

**Self-prompt:** *"If I handed this function a completely unexpected input, what would break?"*

---

## Phase 2 — Security Audit

Treat every external input as hostile.

### Input & Data Handling
- [ ] All user-supplied input is **validated and sanitized** before use.
- [ ] No raw string interpolation into **SQL queries** — use parameterized queries or an ORM.
- [ ] No raw string interpolation into **shell commands** — use safe subprocess APIs with argument lists.
- [ ] **HTML/template output** is escaped to prevent XSS.
- [ ] File paths derived from user input are **canonicalized** and checked against an allowlist or safe root.

### Secrets & Credentials
- [ ] No API keys, passwords, tokens, or secrets are **hardcoded** in the source.
- [ ] Secrets are read from **environment variables or a secrets manager**, never from version-controlled config files.
- [ ] No sensitive data (passwords, PII, tokens) is written to **logs**.

### Authentication & Authorization
- [ ] Every protected endpoint/function checks **authentication** before doing work.
- [ ] Authorization is enforced at the **data layer**, not just the UI layer.
- [ ] No **IDOR** vulnerabilities — users cannot access other users' resources by changing an ID.

### Dependencies
- [ ] Any newly introduced third-party packages are **well-maintained and not deprecated**.
- [ ] No packages with known **critical CVEs** are introduced.

**Self-prompt:** *"What's the worst thing a malicious user could make this code do?"*

---

## Phase 3 — Error Handling & Resilience

Production code must fail gracefully.

- [ ] All **I/O operations** (file, network, database) have try/catch or equivalent error handling.
- [ ] Errors are **logged with enough context** to debug (but without leaking sensitive data).
- [ ] User-facing error messages are **generic** — internal details are never exposed to the end user.
- [ ] Functions that can fail return a clear **error signal** (exception, Result type, error code) rather than silently returning bad data.
- [ ] **Timeouts** are set on any network calls or external service interactions.
- [ ] Retry logic (if present) uses **exponential backoff** and has a max-retry cap.
- [ ] Resources (file handles, DB connections, locks) are released in **finally blocks** or via context managers / RAII — no resource leaks.
- [ ] The code handles **partial failure** gracefully in batch or multi-step operations.

---

## Phase 4 — Performance & Efficiency

Identify problems before they reach production scale.

### Algorithmic Complexity
- [ ] Review all loops. Are there any **O(n²) or worse** patterns that could be flattened with a set/map lookup?
- [ ] Are large collections being **copied unnecessarily**? Use views, generators, or iterators where possible.
- [ ] Are there **redundant computations** inside loops that could be hoisted out?

### Database & I/O
- [ ] Are there **N+1 query patterns**? Batch or join queries where possible.
- [ ] Are queries hitting **indexed columns**? Flag any full-table scans on large datasets.
- [ ] Is **caching** appropriate here? If the same expensive computation is called repeatedly with the same inputs, consider memoization.
- [ ] Are large payloads **streamed** rather than loaded entirely into memory?

### Memory
- [ ] No unbounded data structures that grow indefinitely without eviction.
- [ ] Large objects are released as soon as they are no longer needed.

**Self-prompt:** *"How does this behave with 10x, 100x the expected data volume?"*

---

## Phase 5 — Code Simplification

Simpler code is safer and easier to maintain.

### Eliminate Redundancy
- Deduplicate any logic that appears more than once — extract into a shared function.
- Remove **dead code**: unused variables, unreachable branches, commented-out blocks.
- Replace verbose conditionals with clearer equivalents (early returns, guard clauses, ternaries where readable).

### Reduce Complexity
- If any single function exceeds **~40 lines**, evaluate whether it should be split.
- Nesting deeper than **3 levels** is a smell — refactor with early returns or helper functions.
- Replace **magic numbers and strings** with named constants.
- Prefer **standard library functions** over hand-rolled equivalents.

### Naming & Readability
- Variable and function names should **describe intent**, not implementation (`fetchUserById` not `doThing`).
- Boolean variables and functions should read as assertions: `isActive`, `hasPermission`, `canRetry`.
- Avoid overly abbreviated names unless the abbreviation is universally understood in context.

**Self-prompt:** *"Would a developer unfamiliar with this codebase understand what each function does from its name and signature alone?"*

---

## Phase 6 — Code Style & Consistency

- [ ] Formatting is consistent with the surrounding codebase (indentation, quotes, semicolons, etc.).
- [ ] Imports/dependencies are organized and no unused imports remain.
- [ ] Public functions and complex logic blocks have **docstrings or comments** explaining *why*, not just *what*.
- [ ] Types/type hints are present on all public function signatures (for typed languages/Python with type hints).
- [ ] No `TODO` or `FIXME` comments are left unless they reference a tracked issue.

---

## Phase 7 — Testability & Observability

- [ ] Core logic is in **pure functions** that are easy to unit test in isolation.
- [ ] Side effects (I/O, randomness, time) are **injected or abstracted**, not called directly inside business logic.
- [ ] Key operations emit **structured logs or metrics** that would let an on-call engineer diagnose issues in production.
- [ ] If tests were written as part of the task, do they cover **happy path, edge cases, and failure modes**?
- [ ] If no tests were written, flag the **most critical functions** that should be unit tested and sketch the test cases.

---

## Phase 8 — Final Review Checklist

Run through this list before declaring the code production-ready.

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
| 9 | Critical paths are observable (logging/metrics) | ☐ |
| 10 | Test coverage is adequate or gaps are documented | ☐ |

---

## Output Format — Review Report

After completing all phases, produce a report in this format:

```
## Code Review Report

### ✅ Passed
- [List everything that was already correct]

### 🔧 Fixed
- [Issue]: [What was wrong] → [What was changed and why]

### ⚠️ Flagged for Human Review
- [Issue]: [Why this needs a human decision, e.g. business logic ambiguity, infra-level change]

### 📋 Test Cases to Add
- [Function/scenario]: [What should be tested and why]

### Production Readiness Verdict
**READY** / **READY WITH CAVEATS** / **NOT READY**
Reason: [One sentence summary]
```

---

> **Reminder:** The goal is not to rewrite working code for the sake of it. Make only changes that meaningfully improve safety, correctness, performance, or maintainability. When in doubt about a refactor, flag it rather than change it.
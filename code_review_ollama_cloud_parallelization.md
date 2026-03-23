# Code Review — Ollama Cloud Parallelization

## Scope

- Updated request routing so only local Ollama models are serialized through `OllamaGlobalQueue`.
- Added routing/classification tests for Ollama cloud models (`-cloud`) and selected-model fallback behavior.
- Updated backend/architecture docs to reflect local-vs-cloud Ollama queue behavior.

Changed files:

- `source/llm/router.py`
- `source/services/tab_manager_instance.py`
- `source/services/ollama_global_queue.py`
- `source/services/query_queue.py`
- `tests/test_router.py`
- `tests/test_tab_manager_instance.py`
- `source/CLAUDE_backend.md`
- `docs/architecture.md`

---

## Stage 1 Raw Findings

### Reviewer A — Correctness & Logic

- [MEDIUM] `source/llm/router.py` — `is_local_ollama_model()` originally parsed provider before whitespace normalization, allowing misclassification for values like `" openai/gpt-4o "`.
  - **Fix applied:** normalize with `strip()` before provider parsing; added regression test.

### Reviewer B — Security & Resilience

- No findings.

### Reviewer C — Performance & Quality

- [MEDIUM] `tests/test_tab_manager_instance.py` — initial coverage checked only single-call bypass, not true concurrent execution.
  - **Fix applied:** added concurrent cloud-ollama execution test proving overlap and no global-queue usage.
- [LOW] `tests/test_tab_manager_instance.py` — missing fallback-path coverage when `QueuedQuery.model` is empty and `app_state.selected_model` drives routing.
  - **Fix applied:** added tests for selected-model local and selected-model cloud behavior.

---

## Stage 3 Judge Synthesis (De-dup + Verdict)

### Merged Findings (ranked)

1. **Medium — Provider parsing before normalization in locality helper**
   - Source: Reviewer A
   - Status: **Resolved**

2. **Medium — Missing concurrency-proof test for cloud Ollama bypass**
   - Source: Reviewer C
   - Status: **Resolved**

3. **Low — Missing selected-model fallback routing tests**
   - Source: Reviewer C
   - Status: **Resolved**

### Contradictions

- None.

### False Positives Filtered

- None.

---

## Stage 4 Fix & Verify

### Fixes Applied

- Added `is_local_ollama_model(model_name)` to centralize local/cloud Ollama classification.
- Switched queue gate in `tab_manager_instance._process_fn` from provider check to locality check.
- Ensured classification supports:
  - case-insensitive `-cloud` suffix
  - optional `ollama/` prefix
  - whitespace-trimmed model names
- Expanded tests:
  - router classification tests, including whitespace regression
  - direct cloud Ollama bypass test
  - parallel execution overlap test for two cloud Ollama requests
  - `model=""` fallback routing tests using `app_state.selected_model` (local and cloud)
- Updated docs/comments in queue and architecture files to clarify that only local Ollama is serialized globally.

### Verification Performed

- `uv run python -m pytest tests/test_router.py tests/test_tab_manager_instance.py -v` → **27 passed**
- `uv run python -m pytest tests/test_ollama_global_queue.py tests/test_query_queue.py tests/test_sub_agent.py -v` → **53 passed**
- `uv run python -m pytest tests/ -v` → **939 passed, 4 warnings**
- `uv run ruff check source/llm/router.py source/services/tab_manager_instance.py source/services/query_queue.py tests/test_router.py tests/test_tab_manager_instance.py` → **passed**

Notes:

- `uv run ruff check .` reports pre-existing issues under `Implementation_plans/sample_scraper.py` (outside this change scope).
- `bun run test:frontend` fails due to pre-existing frontend test/mocking drift in `src/ui/test/components/TitleBar.test.tsx` (also outside this change scope and unrelated to backend queue routing).

---

## Production Readiness Verdict

**READY WITH CAVEATS**

The Ollama cloud parallelization fix is complete, tested, and verified for local-vs-cloud routing correctness. Remaining caveats are unrelated pre-existing repo lint/frontend-test issues outside this change scope.

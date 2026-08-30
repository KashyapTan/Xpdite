## Code Review — Final Report (Judge Synthesis)

### Review method

This diff was reviewed against `CODE_REVIEW_GUIDE.md` in three focused passes:
correctness/logic, security/resilience, and performance/quality, followed by a
deduplication/fix pass. The session coordination policy did not permit spawning
reviewer subagents, so these passes were performed independently by the primary agent.

### 🔴 Critical

None.

### 🟠 High

None unresolved.

### 🟡 Medium

None unresolved.

### 🟢 Low

None required before merge.

### ✅ Passed

- Build profiles — the supported platform/architecture matrix, exact dependency groups,
  isolated environments, incompatible-profile failures, and Rosetta rejection match the
  specification.
- Dependency resolution — Intel dry-run resolution selects ONNX Runtime 1.20.1 while
  non-Intel platforms retain the current ONNX Runtime line.
- Packaging — PyInstaller collections and model checks are profile-aware; missing enabled
  packages fail while intentional Intel omissions are explicit.
- Native runtime — PortAudio and other non-system dylibraries are copied, rewritten to
  loader-relative references, and ad-hoc signed before Electron applies its final signature.
  Build-only pytest, Ruff, and PyInstaller files are excluded from the shipped child runtime.
- Native verification — every Mach-O under resource roots and the generated app is checked
  for the target slice; build-host-only absolute dependencies and cache stamps fail the build.
- Runtime behavior — immutable manifest validation fails closed, effective probes downgrade
  only dependent features, and the authenticated endpoint exposes no versions or paths.
- Feature degradation — Intel retains dictation, meeting transcription, native word
  timestamps, and YouTube fallback while alignment, diarization, and bundled local embeddings
  are represented as unavailable rather than failed.
- Renderer — shared capability state is fetched after backend connection, controls use
  backend feature status rather than architecture checks, and rolling-upgrade defaults preserve
  previous behavior.
- CI/release/installer — native Intel verification and release jobs use the exact profile,
  both macOS artifacts are published, and the installer selects the matching architecture.
- Security — subprocesses use argument arrays without a shell, the capability endpoint uses
  existing loopback authentication, secrets are not added, and response reasons remain generic.
- Regression validation — all backend/frontend tests, lint/type checks, runtime import probes,
  Codex handshake, workflow parsing, ARM build, pre-package scan, app scan, and DMG creation pass.

### 🚫 False Positives Discarded

- Absolute dylib install IDs — an install ID is metadata for the library itself, not a load
  dependency. The verifier ignores the ID but still rejects absolute dependencies from callers.
- Capability compatibility defaults — availability defaults to true only when an older backend
  lacks the endpoint, as required for rolling development upgrades; malformed packaged manifests
  fail closed in the backend.
- Optional Google OAuth values — keeping these optional is an explicit specification requirement
  and does not weaken local API authentication.

### 🔧 Changes Made During Review

- Prevented ESLint from scanning generated profile environments.
- Added packaged manifest fixtures to Electron backend-start tests.
- Replaced per-file `file` subprocesses with Mach-O magic detection and correctly handled
  universal `otool` headers and helper names containing parentheses.
- Relocated Homebrew/build-host dylibraries and re-signed modified Mach-O files; verified the
  standalone packaged Python runtime loads its stdlib, PyAudio/PortAudio, CTranslate2,
  ONNX Runtime, and faster-whisper.
- Added explicit Rosetta detection so translated x64 processes cannot publish Intel artifacts.
- Added a profile-aware Python runner so install, development, tests, and builds use the same
  isolated environment after synchronization.
- Pruned build-only Python packages from the shipped runtime and added native Intel speech smoke
  coverage to release automation.
- Expanded Codex build metadata with groups, source identity, and lockfile hash.

### ⚠️ Flagged for Human Review

- The native Intel DMG cannot be produced on the Apple Silicon review host. The implementation
  deliberately rejects cross-architecture/Rosetta builds; the `macos-15-intel` CI/release jobs
  are the authoritative x64 clean-host gate.

### 📋 Follow-up Package Tests

- Launch the signed/notarized x64 DMG on a clean Intel Mac and exercise backend health plus
  `/api/runtime-capabilities` from the packaged renderer.
- Exercise chat, screenshot capture, MCP initialization, and persistence from that clean install.
- Retain the release speech fixture as a required gate and archive its failure logs if native
  dependency availability changes upstream.

### Production Readiness Verdict

**READY WITH CAVEAT** — source, ARM regression packaging, and automated native checks are green;
merge/release remains contingent on the native Intel CI and clean-host package gates passing.

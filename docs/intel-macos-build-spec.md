# Intel macOS Build Support — Implementation Specification

> Status: Proposed
> Scope: Native Intel (`x86_64`) macOS development, packaging, release, and
> runtime capability behavior

## 1. Summary

Xpdite currently publishes an Apple Silicon (`arm64`) macOS package and hard-codes
that architecture in `dist:mac`. An Intel Mac cannot install the complete Python
dependency set because current Torch, Torchaudio, and ONNX Runtime releases do not
all publish compatible macOS `x86_64` wheels. The build also freezes and copies
host-native Python and Codex executables, so changing only Electron's target to
`x64` would produce an invalid mixed-architecture package.

This specification adds a separate native Intel artifact while retaining the
transcription features that have an Intel-compatible implementation. The initial
Intel package will include CTranslate2/faster-whisper transcription and exclude
only the Torch-based advanced audio stack and bundled Sentence Transformers.

The release artifacts will be:

- `Xpdite-<version>-mac-arm64.dmg`: full macOS feature profile.
- `Xpdite-<version>-mac-x64.dmg`: Intel transcription profile.

A universal DMG is intentionally deferred. Separate artifacts make native
dependencies, code signing, test failures, and runtime support boundaries explicit.

## 2. Goals

1. Build and publish a native `x86_64` Xpdite DMG on a native Intel macOS host.
2. Guarantee that every executable and native library in that DMG is Intel-compatible.
3. Preserve basic local transcription on Intel:
   - microphone dictation;
   - live and final meeting transcription;
   - YouTube audio transcription when captions are unavailable.
4. Make advanced audio and embedding dependencies optional at install and package time.
5. Expose build capabilities to the backend and renderer so unavailable features are
   disabled or degraded deliberately.
6. Preserve the existing Apple Silicon and Windows release behavior.
7. Fail early with actionable errors when the host, target, virtual environment, or
   bundled binary architecture is inconsistent.

## 3. Non-goals

- Producing one universal macOS application in the first implementation.
- Cross-compiling a PyInstaller server or Python runtime from Apple Silicon to Intel,
  or from Intel to Apple Silicon.
- Restoring Torch, WhisperX forced alignment, or speaker diarization on Intel by
  compiling unsupported dependencies from source.
- Guaranteeing equal transcription speed between Intel and Apple Silicon.
- Changing provider, chat, screenshot, MCP, mobile bridge, or persistence contracts
  except where runtime capabilities must be surfaced.
- Making Google OAuth credentials mandatory. Google OAuth remains an optional runtime
  capability and is independent of the CPU architecture.

## 4. Current constraints

### 4.1 Electron target

`package.json` maps `dist:mac` directly to `mac arm64`. The distribution wrapper
validates the host operating system but does not verify `process.arch` against the
requested Electron architecture.

### 4.2 Host-native bundled resources

The macOS package contains four architecture-sensitive components:

1. Electron and its native Node dependencies.
2. `dist-python/xpdite-server`, produced by PyInstaller using the active Python.
3. `dist-python-runtime/python`, copied from the active Python base installation and
   virtual environment.
4. `dist-codex-runtime`, selected using the build host's platform and architecture.

All four must use the same target architecture. Electron Builder's `--x64` flag does
not convert the other three components.

### 4.3 Python dependency availability

The current project dependencies mix independent feature domains:

- `faster-whisper` provides ordinary speech-to-text through CTranslate2.
- `pyaudio` captures microphone audio and compiles against PortAudio on macOS.
- `whisperx`, `speechbrain`, `torch`, and `torchaudio` provide forced alignment and
  speaker diarization.
- `sentence-transformers` provides the bundled local embedding fallback.

CTranslate2 publishes a macOS `x86_64` wheel for the Python version used by Xpdite.
The current ONNX Runtime selected transitively by `faster-whisper` does not, but an
Intel-specific `onnxruntime>=1.20,<1.21` constraint resolves to the last compatible
release family. This constraint must be verified continuously in Intel CI.

The current Torch/Torchaudio line does not provide the required Intel macOS wheels.
Those packages must not be selected for the Intel profile.

### 4.4 Packaging assumptions

The PyInstaller build currently assumes Sentence Transformers and its bundled model
are mandatory. It downloads the model during the build, collects ML package metadata
unconditionally, and rejects output that omits those resources. These checks must be
profile-aware rather than globally weakened.

## 5. Supported profile matrix

| Capability | macOS ARM full | macOS Intel transcription |
|---|---:|---:|
| Chat, providers, screenshots, MCP, Codex | Yes | Yes |
| Microphone dictation | Yes | Yes |
| Meeting audio capture | Yes | Yes |
| Live meeting transcription | Yes | Yes |
| Final meeting transcription | Yes | Yes |
| YouTube native-caption extraction | Yes | Yes |
| YouTube Whisper fallback | Yes | Yes |
| Faster-whisper word timestamps | Yes | Yes |
| WhisperX forced alignment | Yes | No |
| Speaker diarization | Yes | No |
| Ollama embedding backend | When configured | When configured |
| Bundled Sentence Transformers | Yes | No |
| BM25/always-on tool retrieval fallback | Yes | Yes |

The Intel build is not described as a generic "slim" build because transcription is
a supported feature. Its canonical profile identifier is `mac-intel-transcription`.
The existing complete profile is `full`.

## 6. Dependency design

### 6.1 Dependency groups

Keep platform-neutral application dependencies in `[project].dependencies`. Move
feature-specific native packages into these dependency groups:

```toml
[dependency-groups]
dev = [
    "pyinstaller>=6.15.0",
    "pytest>=9.0.2",
    "pytest-asyncio>=1.3.0",
]
transcription = [
    "faster-whisper>=1.2.1",
    "pyaudio>=0.2.14",
    "onnxruntime>=1.20,<1.21; sys_platform == 'darwin' and platform_machine == 'x86_64'",
]
advanced-audio = [
    "whisperx>=3.8.1",
    "speechbrain>=1.0.3",
    "torchaudio>=2.8.0",
]
local-embeddings = [
    "sentence-transformers>=5.2.3",
]
```

`torch` may remain transitive unless Xpdite needs to constrain it directly. The lockfile
must be regenerated after the split and committed with the implementation.

The selected groups are:

- `full`: `dev`, `transcription`, `advanced-audio`, and `local-embeddings`.
- `mac-intel-transcription`: `dev` and `transcription` only.

The developer install command must select a profile explicitly or derive it from the
native host. Intel users must not receive the advanced groups through an implicit
default group.

### 6.2 Intel ONNX Runtime constraint

The Intel-only ONNX Runtime constraint exists to satisfy `faster-whisper` without
changing dependency selection on Apple Silicon, Windows, or Linux. Acceptance requires:

1. `uv sync --locked` succeeds on the native Intel release host.
2. `import onnxruntime`, `import ctranslate2`, and `import faster_whisper` succeed.
3. The selected wheels and loaded dynamic libraries report `x86_64`.
4. A fixed WAV transcription fixture produces non-empty text.

If no compatible ONNX Runtime release continues to satisfy Python 3.13, the fallback
decision is to use Python 3.12 only for the Intel artifact. That is a contingency, not
the initial design; it requires a separately locked Intel environment and additional
runtime-version testing.

### 6.3 PortAudio policy

`pyaudio` is built on the release host against Homebrew PortAudio. Homebrew is a build
prerequisite, not an end-user prerequisite.

The package must include the required PortAudio dynamic library. A clean Intel Mac
without Homebrew must be able to launch dictation. The release job must fail if the
PyAudio extension retains an absolute reference to `/usr/local`, `/opt/homebrew`, or
another build-host-only path.

## 7. Build profile contract

### 7.1 Central profile resolution

Add one shared Node build-profile resolver used by dependency sync, build, and
distribution wrappers. It accepts:

- target platform;
- target architecture;
- optional explicit profile override.

It returns the canonical profile, required dependency groups, environment directory,
and expected capabilities. Invalid combinations fail before dependency installation or
packaging. At minimum:

| Platform | Architecture | Profile |
|---|---|---|
| macOS | `arm64` | `full` |
| macOS | `x64` | `mac-intel-transcription` |
| Windows | `x64` | `full` |
| Linux | `x64` | `full` until separately specified |

The build environment passed to child processes includes:

```text
XPDITE_TARGET_PLATFORM
XPDITE_TARGET_ARCH
XPDITE_BUILD_PROFILE
XPDITE_PYTHON_ENV
```

Python scripts consume these values but do not independently guess a different profile.

### 7.2 Package scripts

Add these public commands:

```text
bun run install:python:full
bun run install:python:mac-x64
bun run dist:mac-arm64
bun run dist:mac-x64
```

Keep `bun run dist:mac` as a backward-compatible alias of `dist:mac-arm64`.
`bun run install:python` may auto-select the native profile, but it must print the
resolved target, profile, Python executable, and environment path.

### 7.3 Native host requirement

The first implementation builds each macOS architecture on a matching native host:

- `arm64` on Apple Silicon;
- `x64` on Intel.

`run-electron-dist.mjs` must compare the requested target with `process.arch` and fail
before running the build when they differ. Rosetta and cross-architecture builds may be
added later only after every native resource has explicit target selection and tests.

## 8. Python environments and cache isolation

Use a separate exact-sync environment for each build profile, for example:

```text
.venv-build/macos-arm64-full
.venv-build/macos-x64-mac-intel-transcription
```

The profile resolver sets `UV_PROJECT_ENVIRONMENT` and `XPDITE_PYTHON_ENV` to the
selected directory. Scripts that currently assume `.venv` must resolve Python from
`XPDITE_PYTHON_ENV` first and retain `.venv` only as a development fallback.

Build cache metadata must include:

- schema version;
- target platform and architecture;
- build profile;
- Python executable and `platform.machine()`;
- Python major/minor version;
- selected dependency groups;
- lockfile hash;
- relevant source mtimes or content hashes.

Changing any of these values invalidates `dist-python`, `dist-python-runtime`, and
`dist-codex-runtime`. A locally cached ARM server must never be reused by an Intel build.

## 9. PyInstaller and bundled model behavior

### 9.1 Optional collection

`build-server.spec` must collect packages according to the active profile:

- `full` requires Sentence Transformers, Transformers metadata, the embedding model,
  WhisperX, and the advanced audio packages expected by the current release.
- `mac-intel-transcription` requires faster-whisper, CTranslate2, ONNX Runtime, PyAudio,
  and their native libraries. It skips Sentence Transformers and advanced audio.

Use explicit profile conditions or safe helper functions around `collect_all()` and
`copy_metadata()`. A package missing from an enabled feature is a build error. A package
excluded by the active profile is logged as an intentional omission.

### 9.2 Embedding model preparation

`build-python-exe.py` prepares and validates `all-MiniLM-L6-v2` only when
`local-embeddings` is enabled. For the Intel profile it must:

- skip the Hugging Face download;
- skip package and model presence checks;
- omit the model from PyInstaller data;
- record `local_sentence_embeddings: false` in the build capability manifest.

The full profile retains strict validation so an accidental incomplete official build
does not silently ship.

### 9.3 Native binary verification

Before Electron Builder runs, verify the architecture of:

- `xpdite-server`;
- bundled `python3` and the actual versioned Python executable;
- CTranslate2 native extension;
- ONNX Runtime native extension and libraries;
- PyAudio native extension and bundled PortAudio library;
- Codex executable;
- any other Mach-O file under the packaged resource roots.

Use `file`, `lipo -archs`, or Mach-O inspection with argument-list subprocess calls.
Thin Intel files must contain `x86_64`; universal files are acceptable only when they
contain `x86_64`. ARM-only files fail the Intel build.

After Electron Builder runs, repeat an architecture scan inside the generated `.app`
before creating or publishing the final artifact.

## 10. Runtime capability contract

### 10.1 Build capability manifest

Generate `dist-runtime-config/build-capabilities.json` during every packaged build.
The file is immutable application metadata, not user configuration. Example Intel
manifest:

```json
{
  "schema_version": 1,
  "profile": "mac-intel-transcription",
  "platform": "darwin",
  "architecture": "x64",
  "features": {
    "microphone_dictation": true,
    "meeting_transcription": true,
    "youtube_whisper_fallback": true,
    "whisperx_alignment": false,
    "speaker_diarization": false,
    "local_sentence_embeddings": false
  }
}
```

Electron passes the manifest path to Python similarly to the packaged runtime env file.
Development mode derives capabilities from installed packages when no manifest exists.

### 10.2 Effective capability probing

The backend must not trust the manifest alone. On startup it combines the declared
profile with import/native-load probes:

- transcription requires successful faster-whisper and CTranslate2 loading;
- microphone dictation additionally requires PyAudio and PortAudio loading;
- advanced alignment requires WhisperX and Torch;
- diarization requires the advanced stack and remains separately gated by the user's
  Hugging Face token and model access;
- local Sentence Transformers requires an importable package and a valid bundled model.

If a declared dependency cannot load, the effective feature becomes unavailable and a
structured error is logged. The rest of the backend continues to start.

### 10.3 API shape

Expose effective capabilities through an authenticated loopback endpoint such as
`GET /api/runtime-capabilities`:

```json
{
  "profile": "mac-intel-transcription",
  "platform": "darwin",
  "architecture": "x64",
  "features": {
    "meeting_transcription": {"available": true, "reason": ""},
    "whisperx_alignment": {
      "available": false,
      "reason": "Unavailable in the Intel macOS build."
    }
  }
}
```

The response contains no filesystem paths, package versions, or build-host details that
would unnecessarily expose local environment information.

## 11. Intel transcription behavior

### 11.1 Microphone dictation

Retain the existing PyAudio capture path. Import PyAudio lazily or behind a capability
probe so a native-load failure disables dictation without preventing backend startup.
Starting an unavailable recording returns an explicit user-facing error instead of
silently doing nothing.

### 11.2 Meeting recording

The Intel pipeline remains:

1. Capture and persist PCM/WAV audio through the existing renderer/backend flow.
2. Produce live chunks with faster-whisper using CPU `int8` compute.
3. Produce a final transcript with faster-whisper.
4. Retain faster-whisper segment and native word timestamps.
5. Skip WhisperX forced alignment.
6. Skip speaker diarization.
7. Continue title generation and persistence using the available transcript.

The Intel path must not automatically load `large-v3`. It should use the user's supported
model selection or a CPU-safe default such as `base.en`. Larger models may be exposed
later after benchmarks establish acceptable memory and latency.

An unavailable advanced step is represented as "not supported by this build," not as a
failed recording. Existing recordings remain readable across architectures.

### 11.3 YouTube fallback

Caption extraction is unchanged. When captions are unavailable and the user approves
local transcription, the Intel build uses faster-whisper with the existing CPU/int8 plan.
The approval UI should report the estimated CPU processing time as it does today.

### 11.4 Embedding fallback

The Intel package omits bundled Sentence Transformers. Retrieval order remains:

1. configured Ollama embedding model;
2. bundled Sentence Transformers when present;
3. existing BM25/always-on tool behavior when neither embedding backend is available.

Missing local embeddings must not be described as a general Intel build failure.

## 12. Renderer behavior

Fetch runtime capabilities during application initialization and retain them in shared
state. The renderer must:

- leave microphone, meeting recording, and YouTube transcription controls enabled when
  their Intel probes pass;
- disable or hide speaker diarization controls when unavailable;
- label unavailable advanced processing in recording detail/status views;
- avoid presenting missing WhisperX alignment as an error after a successful transcript;
- show a concise reason when a capability is disabled;
- preserve existing behavior when the capability endpoint is absent during a rolling
  development upgrade by using conservative defaults.

No architecture check should be hard-coded in React. The backend capability response is
the source of truth because native packages can also be absent in development builds.

## 13. Release workflow

### 13.1 Continuous integration

The existing CI matrix includes an Intel macOS runner. Update its Python sync step to use
the Intel transcription profile. CI must run dependency installation, lint, frontend
tests, backend tests, Electron transpilation, and channel bridge compilation on Intel.

Add focused tests for profile selection and optional feature behavior before enabling the
release artifact.

### 13.2 Release jobs

Split the current macOS release job into architecture-specific jobs:

- `build-macos-arm64` on the existing Apple Silicon runner with profile `full`;
- `build-macos-x64` on a native Intel runner with profile
  `mac-intel-transcription`.

Both jobs install PortAudio, synchronize the correct isolated environment, run the Codex
runtime smoke test, build, scan architectures, and upload one DMG. The publish job depends
on and downloads both artifacts.

The existing `${arch}` artifact naming prevents collisions. Signing/notarization policy
must be identical across the two jobs; adding Intel support must not introduce an unsigned
exception.

### 13.3 Installer behavior

Update `scripts/install.sh` to select:

- `mac-arm64.dmg` for `arm64`/`aarch64`;
- `mac-x64.dmg` for `x86_64`.

If the matching release asset is absent, fail with a release-availability message rather
than claiming Intel is unsupported. Installation documentation must list the feature
difference and minimum supported macOS version. Because the CTranslate2 wheel targets
macOS 11 or later, the Intel package minimum may not be lower than macOS 11 without a
different native dependency build.

## 14. Failure handling

Build failures must distinguish:

- unsupported host/target pairing;
- missing dependency group;
- wrong Python architecture;
- missing native wheel;
- missing PortAudio build dependency;
- unbundled or build-host-linked dynamic library;
- mixed-architecture packaged resource;
- missing resource required by the selected profile.

Runtime failures in an optional capability must disable that capability and preserve core
application startup. Runtime failures in core backend initialization retain the existing
fatal startup behavior.

## 15. Security and privacy

- Capability responses reveal only product-level availability and generic reasons.
- Architecture validation invokes system tools without a shell and with explicit paths.
- The Intel package must not include Homebrew metadata, caches, absolute developer paths,
  or unrelated virtual-environment content.
- Downloaded transcription models retain the current local storage and privacy behavior.
- Adding an Intel artifact does not change cloud screenshot consent, provider credential,
  or Google OAuth policies.

## 16. Test requirements

### 16.1 Unit tests

- Profile resolver maps every supported platform/architecture pair correctly.
- Unsupported or mismatched combinations fail before the build starts.
- Dependency sync receives exactly the groups for the selected profile.
- PyInstaller optional collectors distinguish excluded packages from missing required
  packages.
- Model preparation is required for `full` and skipped for Intel.
- Cache stamps invalidate across profile, architecture, Python, and lockfile changes.
- Capability manifest parsing rejects malformed schema and uses safe fallback behavior.
- Effective probes downgrade only the affected capability.
- Meeting post-processing completes without alignment or diarization.
- Installer asset selection maps Intel to `mac-x64.dmg`.

### 16.2 Native Intel integration tests

- Clean `uv sync --locked` for the Intel groups succeeds.
- Native imports for PyAudio, CTranslate2, ONNX Runtime, and faster-whisper succeed.
- A deterministic WAV fixture transcribes to expected non-empty text.
- Microphone service initializes when PortAudio is bundled.
- A meeting fixture produces live/final transcript data without advanced packages.
- YouTube transcription fallback can be tested with mocked download input and a local
  audio fixture.
- Backend health and capability endpoints respond from the packaged app.

### 16.3 Package tests

- Every Mach-O binary in the Intel app is `x86_64` or universal with an `x86_64` slice.
- No packaged Mach-O dependency resolves to a Homebrew-only absolute path.
- The Intel app launches on a clean Intel Mac without Bun, uv, Python, or Homebrew.
- Chat, screenshot capture, Codex startup, and MCP initialization pass smoke tests.
- Dictation, meeting transcription, and YouTube fallback are enabled.
- Alignment, diarization, and bundled Sentence Transformers are reported unavailable.
- Existing ARM and Windows build smoke tests continue to pass.

## 17. Rollout sequence

Implement in focused pull requests:

1. **Build profiles and dependency split**
   - dependency groups, profile resolver, isolated environments, host validation;
   - no Intel release publication yet.
2. **Profile-aware packaging and capabilities**
   - PyInstaller changes, model gating, manifest, runtime probes, renderer behavior.
3. **Intel transcription validation**
   - ONNX constraint, PortAudio bundling, CPU model policy, native integration tests.
4. **Release publication**
   - x64 release job, architecture scan, publish dependencies, installer and user docs.

Each stage must keep ARM and Windows release paths green. The Intel artifact is published
only after the clean-host package tests pass.

## 18. Affected files

Expected implementation areas include:

| Area | Files |
|---|---|
| Dependency profiles | `pyproject.toml`, `uv.lock`, `package.json` |
| Profile resolution and sync | new script under `scripts/`, `scripts/run-electron-dist.mjs` |
| Python server packaging | `scripts/build-python-exe.py`, `build-server.spec` |
| Bundled Python runtime | `scripts/build-python-runtime.mjs` |
| Codex/native architecture validation | `scripts/build-codex-runtime.mjs`, new validation helper/tests |
| Capability manifest | `scripts/build-runtime-env.mjs` or a focused new build script |
| Backend capabilities | `source/infrastructure/config.py`, service/API modules, tests |
| Transcription degradation | media transcription, meeting recorder, and video watcher services |
| Renderer capability UX | shared UI types/services and recording/transcription components |
| CI and release | `.github/workflows/ci.yml`, `.github/workflows/release.yml` |
| Installer and user docs | `scripts/install.sh`, `README.md`, `docs/getting-started.md`, operations/troubleshooting docs |

## 19. Acceptance criteria

Intel macOS support is complete when all of the following are true:

1. `bun run dist:mac-x64` succeeds on a clean native Intel release host.
2. The resulting DMG contains no ARM-only executable or native library.
3. The installed app launches without developer tooling or Homebrew.
4. Core chat, screenshots, Codex, providers, persistence, and MCP functionality work.
5. Microphone dictation, meeting transcription, and YouTube Whisper fallback work using
   faster-whisper on CPU.
6. WhisperX alignment, speaker diarization, and bundled Sentence Transformers are
   intentionally unavailable and clearly represented in the UI.
7. Apple Silicon and Windows release artifacts retain their existing full behavior.
8. Release automation publishes both macOS architecture artifacts and the installer
   selects the correct one.
9. Build and runtime failures identify the affected profile/capability without exposing
   secrets or build-host paths.

## 20. Deferred work

- Benchmarking larger Whisper models and exposing an Intel performance selector.
- Restoring advanced alignment or diarization if maintained Intel-compatible packages
  become available.
- Building Intel artifacts under Rosetta on Apple Silicon.
- Producing and signing a universal application bundle.
- Sharing one downloaded model cache across architecture-specific development environments.

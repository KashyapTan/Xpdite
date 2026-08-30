# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

PROJECT_ROOT = Path.cwd()
BUILD_PROFILE = os.environ.get("XPDITE_BUILD_PROFILE", "full").strip() or "full"
if BUILD_PROFILE not in {"full", "mac-intel-transcription"}:
    raise RuntimeError(f"Unsupported Xpdite PyInstaller profile: {BUILD_PROFILE}")

ENABLE_ADVANCED_AUDIO = BUILD_PROFILE == "full"
ENABLE_LOCAL_EMBEDDINGS = BUILD_PROFILE == "full"
BUNDLED_EMBEDDING_MODEL_DIR = (
    PROJECT_ROOT / "build-temp" / "embedding-models" / "all-MiniLM-L6-v2"
)
SENTENCE_TRANSFORMER_RUNTIME_PACKAGES = [
    "requests",
    "urllib3",
    "idna",
    "charset_normalizer",
    "certifi",
    "packaging",
    "tqdm",
    "typing_extensions",
    "filelock",
    "jinja2",
    "markupsafe",
    "regex",
    "yaml",
]
SENTENCE_TRANSFORMER_RUNTIME_MODULES = [
    "typing_extensions",
]
LITELLM_DATA_FILES = collect_data_files(
    "litellm",
    includes=[
        "anthropic_beta_headers_config.json",
        "containers/*.json",
        "cost.json",
        "integrations/*.json",
        "integrations/generic_api/*.json",
        "litellm_core_utils/tokenizers/*.json",
        "llms/huggingface/huggingface_llms_metadata/*.txt",
        "llms/openai_like/*.json",
        "model_prices_and_context_window_backup.json",
        "policy_templates_backup.json",
    ],
)
LITELLM_METADATA = copy_metadata("litellm")

PROFILE_DATA = []
PROFILE_BINARIES = []
PROFILE_HIDDENIMPORTS = []
PROFILE_METADATA = []


def collect_required(import_name, distribution_name, feature_name):
    if importlib.util.find_spec(import_name) is None:
        raise RuntimeError(
            f"Missing package {distribution_name!r} required by {feature_name} "
            f"for build profile {BUILD_PROFILE!r}. Synchronize the correct dependency groups."
        )
    package_data, package_binaries, package_hiddenimports = collect_all(import_name)
    PROFILE_DATA.extend(package_data)
    PROFILE_BINARIES.extend(package_binaries)
    PROFILE_HIDDENIMPORTS.extend(package_hiddenimports)
    PROFILE_METADATA.extend(copy_metadata(distribution_name))
    print(f"Including {distribution_name} for {feature_name} ({BUILD_PROFILE})")


for package in (
    ("faster_whisper", "faster-whisper"),
    ("ctranslate2", "ctranslate2"),
    ("onnxruntime", "onnxruntime"),
    ("pyaudio", "PyAudio"),
):
    collect_required(*package, "transcription")

if ENABLE_ADVANCED_AUDIO:
    for package in (
        ("whisperx", "whisperx"),
        ("speechbrain", "speechbrain"),
        ("torchaudio", "torchaudio"),
        ("torch", "torch"),
    ):
        collect_required(*package, "advanced audio")
else:
    print("Intentionally omitting WhisperX, SpeechBrain, Torch, and Torchaudio")

if ENABLE_LOCAL_EMBEDDINGS:
    collect_required(
        "sentence_transformers", "sentence-transformers", "local embeddings"
    )
    collect_required("huggingface_hub", "huggingface-hub", "local embeddings")
    for package_name in SENTENCE_TRANSFORMER_RUNTIME_PACKAGES:
        package_data, package_binaries, package_hiddenimports = collect_all(package_name)
        PROFILE_DATA.extend(package_data)
        PROFILE_BINARIES.extend(package_binaries)
        PROFILE_HIDDENIMPORTS.extend(package_hiddenimports)
    PROFILE_HIDDENIMPORTS.extend(SENTENCE_TRANSFORMER_RUNTIME_MODULES)
    for distribution_name in ("transformers", "tokenizers", "safetensors"):
        PROFILE_METADATA.extend(copy_metadata(distribution_name))
else:
    print("Intentionally omitting Sentence Transformers and its bundled model")

EMBEDDING_MODEL_DATA = []
if ENABLE_LOCAL_EMBEDDINGS and BUNDLED_EMBEDDING_MODEL_DIR.exists():
    EMBEDDING_MODEL_DATA.append(
        (
            str(BUNDLED_EMBEDDING_MODEL_DIR),
            "embedding-models/all-MiniLM-L6-v2",
        )
    )

a = Analysis(
    ['source/__main__.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=PROFILE_BINARIES,
    datas=(
        LITELLM_DATA_FILES
        + LITELLM_METADATA
        + PROFILE_DATA
        + PROFILE_METADATA
        + EMBEDDING_MODEL_DATA
    ),
    hiddenimports=[
        'fastapi',
        'crawl4ai',
        'litellm',
        'mcp',
        'mcp.cli',
        'playwright',
        'uvicorn',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'google_auth_oauthlib.flow',
        'google.oauth2.credentials',
        'google.auth.transport.requests',
        'googleapiclient.discovery',
        'google.generativeai',
        'google.genai',
        'ollama',
        'openai',
        'anthropic',
        'httpx',
        'tiktoken',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',
        'pynput',
        'pynput.mouse',
        'pynput.keyboard',
        'PIL',
        'PIL.Image',
        'PIL.ImageGrab',
        'websockets',
        'asyncio',
        'threading',
        'json',
        'socket',
        'sys',
        'os',
        'glob',
        'shutil',
        'time',
        'concurrent.futures'
    ]
    + PROFILE_HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=(
        []
        if BUILD_PROFILE == "full"
        else [
            "sentence_transformers",
            "transformers",
            "whisperx",
            "speechbrain",
            "torch",
            "torchaudio",
            "pyannote",
        ]
    ),
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='xpdite-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='xpdite-server',
)

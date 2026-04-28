# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

PROJECT_ROOT = Path.cwd()
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
SENTENCE_TRANSFORMERS_DATA, SENTENCE_TRANSFORMERS_BINARIES, SENTENCE_TRANSFORMERS_HIDDENIMPORTS = collect_all(
    "sentence_transformers"
)
HUGGINGFACE_HUB_DATA, HUGGINGFACE_HUB_BINARIES, HUGGINGFACE_HUB_HIDDENIMPORTS = collect_all(
    "huggingface_hub"
)
EXTRA_RUNTIME_DATA = []
EXTRA_RUNTIME_BINARIES = []
EXTRA_RUNTIME_HIDDENIMPORTS = []
for package_name in SENTENCE_TRANSFORMER_RUNTIME_PACKAGES:
    package_data, package_binaries, package_hiddenimports = collect_all(package_name)
    EXTRA_RUNTIME_DATA += package_data
    EXTRA_RUNTIME_BINARIES += package_binaries
    EXTRA_RUNTIME_HIDDENIMPORTS += package_hiddenimports
EXTRA_RUNTIME_HIDDENIMPORTS += SENTENCE_TRANSFORMER_RUNTIME_MODULES
SENTENCE_TRANSFORMERS_METADATA = copy_metadata("sentence-transformers")
TRANSFORMERS_METADATA = copy_metadata("transformers")
TOKENIZERS_METADATA = copy_metadata("tokenizers")
HUGGINGFACE_HUB_METADATA = copy_metadata("huggingface-hub")
SAFETENSORS_METADATA = copy_metadata("safetensors")

EMBEDDING_MODEL_DATA = []
if BUNDLED_EMBEDDING_MODEL_DIR.exists():
    EMBEDDING_MODEL_DATA.append(
        (
            str(BUNDLED_EMBEDDING_MODEL_DIR),
            "embedding-models/all-MiniLM-L6-v2",
        )
    )

a = Analysis(
    ['source/__main__.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=(
        SENTENCE_TRANSFORMERS_BINARIES
        + HUGGINGFACE_HUB_BINARIES
        + EXTRA_RUNTIME_BINARIES
    ),
    datas=(
        LITELLM_DATA_FILES
        + LITELLM_METADATA
        + SENTENCE_TRANSFORMERS_DATA
        + HUGGINGFACE_HUB_DATA
        + EXTRA_RUNTIME_DATA
        + SENTENCE_TRANSFORMERS_METADATA
        + TRANSFORMERS_METADATA
        + TOKENIZERS_METADATA
        + HUGGINGFACE_HUB_METADATA
        + SAFETENSORS_METADATA
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
    + SENTENCE_TRANSFORMERS_HIDDENIMPORTS
    + HUGGINGFACE_HUB_HIDDENIMPORTS
    + EXTRA_RUNTIME_HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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

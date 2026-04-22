# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

PROJECT_ROOT = Path.cwd()
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

a = Analysis(
    ['source/__main__.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=LITELLM_DATA_FILES + LITELLM_METADATA,
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
        'ollama',
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
    ],
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
    a.binaries,
    a.datas,
    [],
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

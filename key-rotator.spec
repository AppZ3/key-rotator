# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for key-rotator.
Build with: pyinstaller key-rotator.spec
"""
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ["key_rotator_entry.py"],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle the static PWA files
        ("rotator/static", "rotator/static"),
    ],
    hiddenimports=[
        # Keyring backends
        "keyring.backends",
        "keyring.backends.SecretService",
        "keyring.backends.macOS",
        "keyring.backends.Windows",
        "keyring.backends.fail",
        "secretstorage",
        # APScheduler
        "apscheduler.schedulers.blocking",
        "apscheduler.triggers.cron",
        # FastAPI / uvicorn internals
        "uvicorn.lifespan.on",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "websockets",
        "websockets.legacy",
        "websockets.legacy.server",
        # Provider / store modules
        "rotator.providers.script",
        "rotator.providers.stripe",
        "rotator.providers.resend",
        "rotator.stores.dotenv",
        "rotator.stores.vercel",
        "rotator.stores.system_env",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="key-rotator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # keep console so users can see errors
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

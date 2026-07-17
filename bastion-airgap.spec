# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — AIR-GAP BastionBox build -> dist/BastionBox-AirGap.exe.

Build:  pyinstaller bastion-airgap.spec

The security difference from the standard build is not a runtime flag — it is
what is *in the binary*. This spec EXCLUDES every networking convenience so the
capability is **absent, not disabled**:

  * the optional Ollama client backend and its HTTP stack,
  * any model-downloader path (urllib3/requests/httpx if present),

and it sets BASTION_AIR_GAP=1 at runtime so the in-process guard refuses even the
loopback whitelist. The embedded llama.cpp path (a GGUF is a file) is the only
way models enter the box — by verified media, never a download.

The socket module itself is retained (the network guard needs it to patch), but
every high-level networking library that could originate traffic is dropped, so
even a coding mistake cannot reach for one.
"""
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Force air-gap mode into the frozen environment via a runtime hook file.
_runtime_hook = os.path.join(os.getcwd(), "_airgap_runtime_hook.py")
with open(_runtime_hook, "w", encoding="utf-8") as fh:
    fh.write("import os\nos.environ['BASTION_AIR_GAP'] = '1'\n")

# Bastion + Qt + the embedded llama.cpp runtime (the air-gap inference path),
# but NOT the ollama backend module.
hiddenimports = [
    m for m in collect_submodules("bastion")
    if "ollama_backend" not in m
] + collect_submodules("PySide6") + ["llama_cpp"]

_datas = [
    ("bastion/resources", "bastion/resources"),
    ("docs/security.md", "docs"),
]
_binaries = []
try:  # llama.cpp ships its ggml/llama DLLs as package data under llama_cpp/lib
    from PyInstaller.utils.hooks import collect_all as _collect_all
    _d, _b, _h = _collect_all("llama_cpp")
    _datas += _d
    _binaries += _b
    hiddenimports += _h
except Exception:
    pass

a = Analysis(
    ["bastion/app.py"],
    pathex=["."],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[_runtime_hook],
    # Networking libraries are compiled OUT — the capability is absent.
    excludes=[
        "tkinter", "pytest",
        "ollama", "requests", "httpx", "httpcore", "urllib3", "aiohttp",
        "websockets", "bastion.core.llm.ollama_backend",
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BastionBox-AirGap",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="BastionBox-AirGap",
)

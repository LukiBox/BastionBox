# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — standard BastionBox desktop build -> dist/BastionBox.exe.

Build:  pyinstaller bastion.spec

This is the full build: embedded llama.cpp is supported, and the optional Ollama
backend is available (loopback-only at runtime). For the hardened, network-free
distribution see bastion-airgap.spec, which EXCLUDES networking modules so the
capability is absent rather than merely disabled.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

hiddenimports = (
    collect_submodules("bastion")
    + collect_submodules("PySide6")
    # Office/crypto/inference libs are imported lazily inside functions; name
    # them so the frozen build can read datasheets, write Word/Excel/PDF, and
    # load GGUFs through the embedded llama.cpp runtime.
    + ["docx", "openpyxl", "reportlab", "pypdf", "fitz",
       "cryptography", "argon2", "llama_cpp"]
)
datas = [
    ("bastion/resources", "bastion/resources"),
    ("docs/security.md", "docs"),
]
binaries = []
# Pull data files / native bits for libraries that ship them (PyMuPDF,
# reportlab, and llama.cpp's ggml/llama DLLs under llama_cpp/lib).
for _pkg in ("fitz", "reportlab", "openpyxl", "docx", "llama_cpp"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

a = Analysis(
    ["bastion/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BastionBox",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # a desktop app, not a terminal
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="BastionBox",
)

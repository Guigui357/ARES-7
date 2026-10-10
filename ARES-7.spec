# ARES-7 PyInstaller spec
from PyInstaller.utils.hooks import collect_submodules

APP = "ARES-7"
LOCAL_PACKAGES = ["core", "audio", "stt", "llm", "tts", "tools", "remote", "whatsapp", "gui"]
hiddenimports = []
for package in LOCAL_PACKAGES:
    hiddenimports += collect_submodules(package)

a = Analysis(
    ["ares.py"],
    pathex=["."],
    binaries=[],
    datas=[("config.json", "."), ("web", "web")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

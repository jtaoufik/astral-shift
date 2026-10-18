# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller --noconfirm --distpath dist --workpath build packaging/astral-shift.spec
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
PKG = ROOT / "src" / "astral_shift"
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (PKG / "__init__.py").read_text()).group(1)
BUNDLE_ID = "com.astralpdf.astralshift"

# Optional signing identity, injected by scripts/build-macos.sh (empty = PyInstaller leaves it to us).
IS_MAC = sys.platform == "darwin"

# Qt modules the app never imports (it uses Core, Gui, Widgets, Network, Svg only).
EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtDBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtConcurrent",
    "PySide6.QtPrintSupport", "PySide6.QtXml", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtNetworkAuth", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "tkinter", "unittest", "pytest", "PyInstaller",
]

hidden = ["PIL.ImageFont", "PIL.ImageDraw", "PIL.ImageFilter", "PIL.ExifTags"]
# Imported lazily inside watcher.py, so the analysis cannot see them.
if IS_MAC:
    hidden += ["AppKit", "Foundation", "objc", "Quartz"]
else:
    hidden += ["Xlib", "Xlib.display", "Xlib.ext", "Xlib.ext.record", "Xlib.protocol", "Xlib.support"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Astral Shift" if IS_MAC else "astral-shift",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=not IS_MAC,
    icon=str(ROOT / "packaging" / "icon.icns") if IS_MAC else None,
    # Signing is done by scripts/build-macos.sh (inside-out, hardened runtime).
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Astral Shift" if IS_MAC else "astral-shift")

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Astral Shift.app",
        icon=str(ROOT / "packaging" / "icon.icns"),
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": "Astral Shift",
            "CFBundleDisplayName": "Astral Shift",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "Copyright Taoufik Jabbari. AGPL-3.0-or-later.",
            "NSAppleEventsUsageDescription": "Astral Shift reads the files selected in Finder when you press its shortcut.",
        },
    )

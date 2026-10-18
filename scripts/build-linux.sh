#!/usr/bin/env bash
# Build dist/AstralShift-Linux-x86_64.AppImage (run on ubuntu-22.04 for an old glibc baseline).
# Needs: python with pyinstaller + deps, curl. Qt xcb runtime libs are needed to RUN, not to build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"; elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi

ARCH=x86_64
OUT="dist/AstralShift-Linux-$ARCH.AppImage"
TOOLS="${APPIMAGE_TOOLS_DIR:-$ROOT/build/tools}"
mkdir -p "$TOOLS"

echo "== PyInstaller"
rm -rf dist build/astral-shift build/AppDir
mkdir -p build
"$PY" -m PyInstaller --noconfirm --distpath dist --workpath build/pyi packaging/astral-shift.spec
[ -x dist/astral-shift/astral-shift ] || { echo "no binary produced" >&2; exit 1; }

echo "== AppDir"
AD=build/AppDir
mkdir -p "$AD/usr/lib" "$AD/usr/share/applications" "$AD/usr/share/icons/hicolor/512x512/apps"
cp -R dist/astral-shift "$AD/usr/lib/astral-shift"
cat > "$AD/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/astral-shift/astral-shift" "$@"
RUN
chmod +x "$AD/AppRun"
cp packaging/astral-shift.desktop "$AD/astral-shift.desktop"
cp packaging/astral-shift.desktop "$AD/usr/share/applications/"
cp packaging/icon.png "$AD/astral-shift.png"
cp packaging/icon.png "$AD/.DirIcon"
cp -R packaging/hicolor/. "$AD/usr/share/icons/hicolor/"

echo "== appimagetool"
command -v desktop-file-validate >/dev/null || { echo "install desktop-file-utils (apt) first" >&2; exit 1; }
AIT="$TOOLS/appimagetool-$ARCH.AppImage"
if [ ! -x "$AIT" ]; then
  curl -fsSL -o "$AIT" "https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-$ARCH.AppImage"
  chmod +x "$AIT"
fi
# --appimage-extract-and-run: no FUSE needed (CI containers).
ARCH=$ARCH "$AIT" --appimage-extract-and-run --no-appstream "$AD" "$OUT"
chmod +x "$OUT"
ls -lh "$OUT"

#!/usr/bin/env bash
# Build, sign (Developer ID, hardened runtime), notarize and staple the macOS DMG.
#   scripts/build-macos.sh            -> dist/AstralShift-macOS-<arch>.dmg
# Env overrides:
#   SIGN_IDENTITY   default "Developer ID Application: Taoufik Jabbari (URB3N9DX5X)"
#   NOTARY_KEY      path to the ASC .p8   (default ~/.appstoreconnect/private_keys/AuthKey_5M266KQ46M.p8)
#   NOTARY_KEY_ID / NOTARY_ISSUER
#   SKIP_NOTARIZE=1 build + sign only
#   PYTHON          python with pyinstaller + deps (default: .venv/bin/python, else python3)
# No entitlements file: the hardened-runtime bundle launches fine without one (verified), since every
# Mach-O is signed with the same team ID.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IDENTITY="${SIGN_IDENTITY:-Developer ID Application: Taoufik Jabbari (URB3N9DX5X)}"
KEY="${NOTARY_KEY:-$HOME/.appstoreconnect/private_keys/AuthKey_5M266KQ46M.p8}"
KEY_ID="${NOTARY_KEY_ID:-5M266KQ46M}"
ISSUER="${NOTARY_ISSUER:-0f329102-99f5-4d60-9da0-f2b86441abf8}"
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"; elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi

case "$(uname -m)" in arm64) ARCH=arm64 ;; x86_64) ARCH=x86_64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
APP_NAME="Astral Shift"
APP="dist/$APP_NAME.app"
DMG="dist/AstralShift-macOS-$ARCH.dmg"

log() { printf '\n== %s\n' "$*"; }

log "PyInstaller ($ARCH)"
rm -rf build dist
"$PY" -m PyInstaller --noconfirm --distpath dist --workpath build packaging/astral-shift.spec
[ -d "$APP" ] || { echo "no $APP produced" >&2; exit 1; }
# PyInstaller's onedir COLLECT folder next to the .app is not shipped.
rm -rf "dist/$APP_NAME"

log "codesign nested code (inside-out)"
# Every Mach-O (dylib, so, executables, Qt frameworks' binaries), deepest paths first.
while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q 'Mach-O'; then printf '%s\t%s\n' "${#f}" "$f"; fi
done < <(find "$APP" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.so' \) -print0) \
  | sort -rn | cut -f2- \
  | while IFS= read -r f; do
      codesign --force --timestamp --options runtime --sign "$IDENTITY" "$f"
    done
# Frameworks (Qt) as bundles, deepest first, then the app.
find "$APP" -type d -name '*.framework' | awk '{print length($0) "\t" $0}' | sort -rn | cut -f2- \
  | while IFS= read -r fw; do codesign --force --timestamp --options runtime --sign "$IDENTITY" "$fw"; done

log "codesign app"
codesign --force --timestamp --options runtime --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

log "DMG"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO -fs HFS+ "$DMG"
rm -rf "$STAGE"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

if [ "${SKIP_NOTARIZE:-0}" = "1" ]; then echo "SKIP_NOTARIZE=1: done (not notarized): $DMG"; exit 0; fi

log "notarize"
xcrun notarytool submit "$DMG" --key "$KEY" --key-id "$KEY_ID" --issuer "$ISSUER" --wait 2>&1 | tee build/notary.log
grep -q 'status: Accepted' build/notary.log || { echo "notarization not accepted" >&2; exit 1; }
# stapler talks to CloudKit, which drops connections now and then on CI runners: retry.
for i in 1 2 3 4 5; do
  if xcrun stapler staple "$DMG" && xcrun stapler validate "$DMG"; then break; fi
  [ "$i" = 5 ] && { echo "stapling failed" >&2; exit 1; }
  sleep 15
done

log "verify"
MNT="$(mktemp -d)"
hdiutil attach "$DMG" -mountpoint "$MNT" -nobrowse -readonly -quiet
trap 'hdiutil detach "$MNT" -quiet || true' EXIT
spctl -a -vv "$MNT/$APP_NAME.app" 2>&1 | tee build/spctl.log
grep -q 'source=Notarized Developer ID' build/spctl.log
"$MNT/$APP_NAME.app/Contents/MacOS/$APP_NAME" --version
ls -lh "$DMG"

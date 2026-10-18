"""Open at login: a LaunchAgent on macOS, an XDG autostart entry on Linux."""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from .. import APP_ID


def _launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        # Inside an .app bundle, open the bundle so macOS treats it as the app.
        for parent in exe.parents:
            if parent.suffix == ".app":
                return ["/usr/bin/open", "-a", str(parent)]
        appimage = os.environ.get("APPIMAGE")
        return [appimage] if appimage else [str(exe)]
    return [sys.executable, "-m", "astral_shift"]


def entry_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "autostart" / "astral-shift.desktop"


def is_enabled() -> bool:
    return entry_path().exists()


def render() -> str:
    cmd = _launch_command()
    if sys.platform == "darwin":
        args = "".join(f"\n        <string>{a}</string>" for a in cmd)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{APP_ID}</string>
    <key>ProgramArguments</key>
    <array>{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    return (
        "[Desktop Entry]\nType=Application\nName=Astral Shift\n"
        f"Exec={shlex.join(cmd)}\nIcon=astral-shift\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
    )


def set_enabled(on: bool) -> None:
    path = entry_path()
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render())
    elif path.exists():
        path.unlink()

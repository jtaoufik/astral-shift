"""Right-click menu entries in the file manager.

* macOS: a Finder Quick Action, "Astral Shift", in ~/Library/Services.
* Linux: a Nautilus script, a Dolphin service menu and a Nemo action.

Each entry runs ``astral-shift wheel <files>``, which opens the wheel with
the selected files in the running app (or starts it).
"""
from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from . import autostart

MENU_TITLE = "Astral Shift"


def wheel_command() -> list[str]:
    """Command that opens the wheel; file paths are appended."""
    cmd = autostart._launch_command()
    if cmd[:2] == ["/usr/bin/open", "-a"]:  # inside an .app: call the binary itself
        cmd = [str(Path(sys.executable))]
    return cmd + ["wheel"]


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def entry_paths() -> list[Path]:
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Services" / f"{MENU_TITLE}.workflow"]
    data = _data_home()
    return [
        data / "nautilus" / "scripts" / MENU_TITLE,
        data / "kio" / "servicemenus" / "astral-shift.desktop",
        data / "nemo" / "actions" / "astral-shift.nemo_action",
    ]


def is_installed() -> bool:
    return any(p.exists() for p in entry_paths())


# --- macOS Quick Action ------------------------------------------------------------

def _arg(name: str, default, uuid: int) -> dict:
    return {"default value": default, "name": name, "required": "0", "type": "0", "uuid": str(uuid)}


def quick_action_plists(command: str) -> tuple[dict, dict]:
    """(Info.plist, document.wflow) for a Finder Quick Action running ``command "$@"``."""
    info = {
        "NSServices": [{
            "NSBackgroundColorName": "background",
            "NSIconName": "NSActionTemplate",
            "NSMenuItem": {"default": MENU_TITLE},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": ["com.adobe.pdf", "public.image"],
        }],
    }
    action = {
        "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
        "AMActionVersion": "2.0.3",
        "AMApplication": ["Automator"],
        "AMParameterProperties": {k: {} for k in ("COMMAND_STRING", "CheckedForUserDefaultShell", "inputMethod", "shell", "source")},
        "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
        "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
        "ActionName": "Run Shell Script",
        "ActionParameters": {
            # Detach so Automator's gear does not spin while the app runs.
            "COMMAND_STRING": f'{command} "$@" >/dev/null 2>&1 &',
            "CheckedForUserDefaultShell": True,
            "inputMethod": 1,  # selected files as arguments
            "shell": "/bin/zsh",
            "source": "",
        },
        "BundleIdentifier": "com.apple.RunShellScript",
        "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False,
        "CanShowWhenRun": True,
        "Category": ["AMCategoryUtilities"],
        "Class Name": "RunShellScriptAction",
        "InputUUID": "6E1B7C52-6E0B-4C1E-9A6B-0F2F3B9D1A01",
        "OutputUUID": "6E1B7C52-6E0B-4C1E-9A6B-0F2F3B9D1A02",
        "UUID": "6E1B7C52-6E0B-4C1E-9A6B-0F2F3B9D1A03",
        "UnlocalizedApplications": ["Automator"],
        "arguments": {
            "0": _arg("inputMethod", 0, 0),
            "1": _arg("CheckedForUserDefaultShell", False, 1),
            "2": _arg("source", "", 2),
            "3": _arg("COMMAND_STRING", "", 3),
            "4": _arg("shell", "/bin/sh", 4),
        },
        "conversionLabel": 0,
        "isViewVisible": 1,
        "location": "309.000000:305.000000",
        "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
    }
    doc = {
        "AMApplicationBuild": "534",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{"action": action, "isViewVisible": 1}],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    return info, doc


# --- Linux ----------------------------------------------------------------------------

def nautilus_script(command: str) -> str:
    # Nautilus passes the selection as arguments.
    return f'#!/bin/sh\nexec {command} "$@"\n'


def dolphin_menu(command: str) -> str:
    return (
        "[Desktop Entry]\nType=Service\nX-KDE-ServiceTypes=KonqPopupMenu/Plugin\n"
        "MimeType=application/pdf;image/png;image/jpeg;image/webp;image/bmp;image/tiff;image/gif;\n"
        "Actions=astralShift;\nX-KDE-Priority=TopLevel\n\n"
        f"[Desktop Action astralShift]\nName={MENU_TITLE}\nIcon=astral-shift\nExec={command} %F\n"
    )


def nemo_action(command: str) -> str:
    return (
        "[Nemo Action]\n"
        f"Name={MENU_TITLE}\nComment=Open the Astral Shift wheel\nExec={command} %F\n"
        "Icon-Name=astral-shift\nSelection=notnone\nExtensions=pdf;png;jpg;jpeg;webp;bmp;tif;tiff;gif;\n"
    )


# --- install / remove -----------------------------------------------------------------------

def install() -> list[Path]:
    command = shlex.join(wheel_command())
    paths = entry_paths()
    if sys.platform == "darwin":
        bundle = paths[0] / "Contents"
        bundle.mkdir(parents=True, exist_ok=True)
        info, doc = quick_action_plists(command)
        (bundle / "Info.plist").write_bytes(plistlib.dumps(info))
        (bundle / "document.wflow").write_bytes(plistlib.dumps(doc))
        refresh_services()
        return paths
    writers = [nautilus_script, dolphin_menu, nemo_action]
    for path, write in zip(paths, writers):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(write(command))
        path.chmod(0o755)  # Nautilus and Dolphin only run executable entries
    return paths


def uninstall() -> None:
    import shutil
    for p in entry_paths():
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    if sys.platform == "darwin":
        refresh_services()


def refresh_services() -> None:
    """Ask macOS to re-read the Services menu now rather than at next login."""
    try:
        subprocess.run(["/System/Library/CoreServices/pbs", "-update"], timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def set_installed(on: bool) -> None:
    install() if on else uninstall()

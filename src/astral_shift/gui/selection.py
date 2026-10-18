"""Files currently selected in the file manager, for the keyboard shortcut.

macOS asks once for permission to talk to Finder (Automation). Linux file
managers expose no common API for this, so the shortcut opens an empty
wheel that files can be dropped on.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import ops

FINDER_SCRIPT = '''
set out to ""
tell application "Finder"
    repeat with f in (get selection)
        set out to out & POSIX path of (f as alias) & linefeed
    end repeat
end tell
return out
'''


def finder_selection(timeout: float = 3.0) -> list[Path]:
    if sys.platform != "darwin":
        return []
    try:
        done = subprocess.run(["osascript", "-e", FINDER_SCRIPT], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if done.returncode != 0:
        return []
    paths = [Path(line) for line in done.stdout.splitlines() if line.strip()]
    return [p for p in paths if p.is_file() and ops.is_supported(p)]

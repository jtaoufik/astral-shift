import sys

import pytest

from astral_shift.gui import autostart, single


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    return tmp_path


def test_macos_launch_agent(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    path = autostart.entry_path()
    assert path == home / "Library/LaunchAgents/com.astralpdf.astralshift.plist"
    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    text = path.read_text()
    assert "<string>-m</string>" in text and "RunAtLoad" in text
    autostart.set_enabled(False)
    assert not path.exists()
    autostart.set_enabled(False)  # already off


def test_linux_desktop_entry(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "cfg"))
    autostart.set_enabled(True)
    text = (home / "cfg/autostart/astral-shift.desktop").read_text()
    assert text.startswith("[Desktop Entry]") and "-m astral_shift" in text


def test_frozen_commands(home, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/Astral Shift.app/Contents/MacOS/Astral Shift")
    assert autostart._launch_command() == ["/usr/bin/open", "-a", "/Applications/Astral Shift.app"]
    monkeypatch.setattr(sys, "executable", "/tmp/.mount_x/usr/bin/astral-shift")
    assert autostart._launch_command() == ["/tmp/.mount_x/usr/bin/astral-shift"]
    monkeypatch.setenv("APPIMAGE", "/home/me/AstralShift.AppImage")
    assert autostart._launch_command() == ["/home/me/AstralShift.AppImage"]


def test_single_instance_roundtrip(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(single, "NAME", f"astral-test-{tmp_path.name}")
    assert not single.send_to_running("wheel", timeout_ms=100)
    server = single.Server()
    assert server.listen()
    with qtbot.waitSignal(server.message, timeout=3000) as got:
        assert single.send_to_running("wheel")
    assert got.args == ["wheel"]
    # A second server takes over a stale name (the first one "crashed").
    other = single.Server()
    assert other.listen()

import runpy
import sys

import pymupdf
import pytest
from PIL import Image

from astral_shift import cli


def run(*args):
    return cli.main(list(map(str, args)))


def test_convert_and_print(pdf, capsys):
    assert run("convert", pdf, "--to", "png", "--dpi", 50) == 0
    out = capsys.readouterr().out.splitlines()
    assert [l.rsplit("/", 1)[-1] for l in out] == ["Page 001 p1.png", "Page 001 p2.png"]


def test_every_command(jpg, pdf, capsys):
    assert run("compress", jpg, "--level", "high") == 0
    assert run("crop", jpg, "--rect", 0, 0, 0.5, 0.5) == 0
    assert run("rotate", jpg, "--degrees", 180) == 0
    assert run("background", jpg, "--preset", "ocean", "--ratio", "16:9") == 0
    assert run("redact", pdf, "--rect", 0, 0, 1, 0.2, "--page", 2) == 0
    assert run("metadata", jpg, "--strip") == 0
    names = [l.rsplit("/", 1)[-1] for l in capsys.readouterr().out.splitlines()]
    assert names == ["Photo Compressed.jpg", "Photo Cropped.jpg", "Photo Rotated.jpg",
                     "Photo with Background.png", "Page 001 Redacted.pdf", "Photo Clean.jpg"]


def test_metadata_listing(jpg, capsys):
    assert run("metadata", jpg) == 0
    assert "Artist: Jane Doe" in capsys.readouterr().out


@pytest.mark.parametrize("args, msg", [
    (["background", "--preset", "nope"], "Unknown preset"),
    (["background", "--ratio", "7:3"], "Unknown ratio"),
    (["convert", "--to", "jpg"], "Cannot convert"),
])
def test_errors_are_reported_and_other_files_continue(jpg, png, capsys, args, msg):
    assert cli.main([args[0], str(jpg), str(png), *args[1:]]) == 1
    captured = capsys.readouterr()
    assert msg in captured.err


def test_unknown_command_is_rejected():
    import argparse
    ns = argparse.Namespace(cmd="bogus", files=["x"])
    assert cli.run(ns) == 1


def test_version(capsys):
    with pytest.raises(SystemExit):
        run("--version")
    assert "astral-shift 0.1.0" in capsys.readouterr().out


def test_no_args_starts_gui(monkeypatch):
    import astral_shift.gui.app as app
    monkeypatch.setattr(app, "run_app", lambda: 7)
    assert cli.main([]) == 7
    assert cli.main(["gui"]) == 7


def test_wheel_command(monkeypatch, capsys):
    import astral_shift.gui.single as single
    monkeypatch.setattr(single, "send_to_running", lambda msg: False)
    assert cli.main(["wheel"]) == 1
    assert "not running" in capsys.readouterr().err
    monkeypatch.setattr(single, "send_to_running", lambda msg: msg == "wheel")
    assert cli.main(["wheel"]) == 0


def test_module_entry_points(monkeypatch, jpg):
    monkeypatch.setattr(sys, "argv", ["astral-shift", "metadata", str(jpg)])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("astral_shift", run_name="__main__")
    assert e.value.code == 0
    monkeypatch.setattr(sys, "argv", ["astral-shift", "metadata", str(jpg)])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("astral_shift.cli", run_name="__main__")
    assert e.value.code == 0

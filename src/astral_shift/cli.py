"""Command line: ``astral-shift`` with no arguments starts the app.

    astral-shift convert "Page 001.pdf" --to jpg
    astral-shift compress scan.pdf --level high
    astral-shift crop photo.jpg --rect 0.1 0.1 0.9 0.9
    astral-shift rotate photo.jpg --degrees 90
    astral-shift background shot.png --preset ocean --ratio 16:9
    astral-shift metadata photo.jpg [--strip]
    astral-shift wheel        # show the wheel at the cursor (bind it to a shortcut on Wayland)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__


def _rect(values: list[str]) -> tuple[float, float, float, float]:
    return tuple(float(v) for v in values)  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astral-shift", description=f"{APP_NAME}: hold Shift while dragging a file.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("convert", help="convert PDF <-> images")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--to", help="target format: jpg, png, webp, pdf (default: jpg for PDFs, pdf for images)")
    s.add_argument("--dpi", type=int, default=200)

    s = sub.add_parser("compress", help="make files smaller")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--level", choices=["low", "medium", "high"], default="medium")

    s = sub.add_parser("crop", help="crop to a normalised rect (0..1)")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--rect", nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))

    s = sub.add_parser("rotate", help="rotate clockwise")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--degrees", type=int, default=90, choices=[90, 180, 270])

    s = sub.add_parser("background", help="put the file on a gradient background (PNG)")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--preset", default="sunset")
    s.add_argument("--ratio", default="auto")
    s.add_argument("--padding", type=float, default=0.12)
    s.add_argument("--radius", type=float, default=0.03)
    s.add_argument("--shadow", type=float, default=0.5)

    s = sub.add_parser("redact", help="black out a normalised rect on a page (PDF text is removed)")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--rect", nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    s.add_argument("--page", type=int, default=1, help="1-based page number")

    s = sub.add_parser("metadata", help="show metadata, or strip it")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--strip", action="store_true")

    sub.add_parser("wheel", help="ask the running app to show the wheel at the cursor")
    sub.add_parser("gui", help="start the app (default)")
    return p


def run(args: argparse.Namespace) -> int:
    from . import ops

    status = 0
    for f in getattr(args, "files", []):
        try:
            if args.cmd == "convert":
                outs = ops.convert(f, args.to, dpi=args.dpi)
            elif args.cmd == "compress":
                outs = [ops.compress(f, args.level)]
            elif args.cmd == "crop":
                outs = [ops.crop(f, _rect(args.rect))]
            elif args.cmd == "rotate":
                outs = [ops.rotate(f, args.degrees)]
            elif args.cmd == "background":
                if args.preset not in ops.PRESETS:
                    raise ValueError(f"Unknown preset {args.preset}; one of {', '.join(ops.PRESETS)}")
                if args.ratio not in ops.RATIOS:
                    raise ValueError(f"Unknown ratio {args.ratio}; one of {', '.join(ops.RATIOS)}")
                bg = ops.Background(ops.PRESETS[args.preset], args.padding, args.radius, args.shadow, args.ratio)
                outs = [ops.add_background(f, bg)]
            elif args.cmd == "redact":
                outs = [ops.redact(f, {args.page - 1: [_rect(args.rect)]})]
            elif args.cmd == "metadata":
                if args.strip:
                    outs = [ops.strip_metadata(f)]
                else:
                    print(f"{f}:")
                    for k, v in ops.read_metadata(f).items():
                        print(f"  {k}: {v}")
                    continue
            else:  # pragma: no cover
                raise ValueError(args.cmd)
            for o in outs:
                print(o)
        except Exception as e:  # report and carry on with the next file
            print(f"astral-shift: {f}: {e}", file=sys.stderr)
            status = 1
    return status


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui.app import run_app
        return run_app()
    if args.cmd == "wheel":
        from .gui.single import send_to_running
        if not send_to_running("wheel"):
            print("astral-shift: the app is not running", file=sys.stderr)
            return 1
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

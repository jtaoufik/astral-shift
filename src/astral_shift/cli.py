"""Command line: ``astral-shift`` with no arguments starts the app.

    astral-shift convert "Page 001.pdf" --to jpg
    astral-shift compress scan.pdf --level high
    astral-shift crop photo.jpg --rect 0.1 0.1 0.9 0.9
    astral-shift rotate photo.jpg --degrees 90
    astral-shift background shot.png --preset ocean --ratio 16:9
    astral-shift metadata photo.jpg [--strip]
    astral-shift merge a.pdf b.pdf photo.jpg [--out all.pdf]
    astral-shift split report.pdf
    astral-shift wheel [files...]   # show the wheel (bind to a shortcut on Wayland)
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

    s = sub.add_parser("merge", help="join PDFs and images into one PDF, in order")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--out", type=Path, help="output file (default: '<first> Merged.pdf')")

    s = sub.add_parser("split", help="one PDF per page")
    s.add_argument("files", nargs="+", type=Path)

    s = sub.add_parser("wheel", help="show the wheel at the cursor, for these files if given (starts the app if needed)")
    s.add_argument("files", nargs="*", type=Path)
    sub.add_parser("gui", help="start the app (default)")
    return p


def run(args: argparse.Namespace) -> int:
    from . import ops

    if args.cmd == "merge":
        try:
            print(ops.merge(args.files, args.out))
            return 0
        except Exception as e:
            print(f"astral-shift: {e}", file=sys.stderr)
            return 1
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
            elif args.cmd == "split":
                outs = ops.split(f)
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
        from .gui.app import run_app
        return run_app([f.resolve() for f in args.files])
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

"""Redaction and annotation.

Both take marks per page (images have a single page 0) in normalised
coordinates. PDF redaction is real: the text, vector art and image pixels
under each box are removed from the file, not just covered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from .convert import save_image
from .files import kind, output_path

Rect = tuple[float, float, float, float]
Point = tuple[float, float]
Color = tuple[int, int, int]


def _page_rect(page: pymupdf.Page, r: Rect) -> pymupdf.Rect:
    """Normalised rect as the user saw the page -> PyMuPDF's unrotated space."""
    pr = page.rect
    rect = pymupdf.Rect(pr.x0 + r[0] * pr.width, pr.y0 + r[1] * pr.height,
                        pr.x0 + r[2] * pr.width, pr.y0 + r[3] * pr.height) * page.derotation_matrix
    rect.normalize()
    return rect


def _px(r: Rect, size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    x0, x1 = sorted((r[0], r[2]))
    y0, y1 = sorted((r[1], r[3]))
    return round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)


def redact(path: Path, boxes: dict[int, list[Rect]]) -> Path:
    path = Path(path)
    if not any(boxes.values()):
        raise ValueError("Nothing to redact")
    dest = output_path(path, "Redacted")
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            for index, rects in boxes.items():
                if not rects:
                    continue
                page = doc[index]
                for r in rects:
                    page.add_redact_annot(_page_rect(page, r), fill=(0, 0, 0))
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                )
            doc.scrub(metadata=False, xml_metadata=False)
            doc.save(dest, garbage=4, deflate=True, clean=True)
        return dest
    with Image.open(path) as im:
        im.load()
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        draw = ImageDraw.Draw(im)
        for r in boxes.get(0, []):
            draw.rectangle(_px(r, im.size), fill=(0, 0, 0))
        im.info.pop("exif", None)
        return save_image(im, dest)


@dataclass
class Mark:
    """One annotation. ``kind`` is pen, highlight, rect, arrow or text."""
    kind: str
    points: list[Point] = field(default_factory=list)  # pen/highlight: path; rect/arrow: 2 points; text: 1
    color: Color = (255, 59, 48)
    width: float = 0.004  # stroke, fraction of the page's longer side
    text: str = ""
    size: float = 0.03  # text height, fraction of the page's longer side


def _arrow_head(p0: Point, p1: Point, length: float) -> tuple[Point, Point]:
    import math
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    spread = math.radians(28)
    return (
        (p1[0] - length * math.cos(ang - spread), p1[1] - length * math.sin(ang - spread)),
        (p1[0] - length * math.cos(ang + spread), p1[1] - length * math.sin(ang + spread)),
    )


def _font(px: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc", "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


def draw_marks_on_image(im: Image.Image, marks: list[Mark]) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    longest = max(w, h)
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for m in marks:
        pts = [(x * w, y * h) for x, y in m.points]
        stroke = max(1, round(m.width * longest))
        if m.kind == "pen" and len(pts) > 1:
            draw.line(pts, fill=m.color + (255,), width=stroke, joint="curve")
        elif m.kind == "highlight" and len(pts) > 1:
            draw.line(pts, fill=m.color + (110,), width=stroke * 5, joint="curve")
        elif m.kind == "rect" and len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            draw.rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), outline=m.color + (255,), width=stroke)
        elif m.kind == "arrow" and len(pts) >= 2:
            p0, p1 = pts[0], pts[-1]
            draw.line([p0, p1], fill=m.color + (255,), width=stroke)
            a, b = _arrow_head(p0, p1, stroke * 5)
            draw.polygon([p1, a, b], fill=m.color + (255,))
        elif m.kind == "text" and pts and m.text:
            draw.text(pts[0], m.text, fill=m.color + (255,), font=_font(max(8, round(m.size * longest))))
    return Image.alpha_composite(im, overlay)


def _draw_marks_on_page(page: pymupdf.Page, marks: list[Mark]) -> None:
    pr = page.rect
    longest = max(pr.width, pr.height)
    derotate = page.derotation_matrix
    to_page = lambda p: pymupdf.Point(pr.x0 + p[0] * pr.width, pr.y0 + p[1] * pr.height) * derotate  # noqa: E731
    for m in marks:
        color = tuple(c / 255 for c in m.color)
        stroke = max(0.5, m.width * longest)
        pts = [to_page(p) for p in m.points]
        shape = page.new_shape()
        if m.kind in ("pen", "highlight") and len(pts) > 1:
            shape.draw_polyline(pts)
            if m.kind == "highlight":
                shape.finish(color=color, width=stroke * 5, stroke_opacity=0.43, lineCap=1, lineJoin=1, closePath=False)
            else:
                shape.finish(color=color, width=stroke, lineCap=1, lineJoin=1, closePath=False)
        elif m.kind == "rect" and len(pts) >= 2:
            r = pymupdf.Rect(pts[0], pts[-1])
            r.normalize()
            shape.draw_rect(r)
            shape.finish(color=color, width=stroke)
        elif m.kind == "arrow" and len(pts) >= 2:
            p0, p1 = pts[0], pts[-1]
            shape.draw_line(p0, p1)
            shape.finish(color=color, width=stroke)
            a, b = _arrow_head((p0.x, p0.y), (p1.x, p1.y), stroke * 5)
            shape.draw_polyline([p1, pymupdf.Point(a), pymupdf.Point(b)])
            shape.finish(color=color, fill=color, width=0, closePath=True)
        elif m.kind == "text" and pts and m.text:
            size = max(4, m.size * longest)
            # Baseline one line below the click, in the visible orientation.
            origin = pymupdf.Point(m.points[0][0] * pr.width, m.points[0][1] * pr.height + size) * derotate
            shape.insert_text(origin, m.text, fontsize=size, color=color, rotate=page.rotation)
        else:
            continue
        shape.commit(overlay=True)


def annotate(path: Path, marks: dict[int, list[Mark]]) -> Path:
    path = Path(path)
    if not any(marks.values()):
        raise ValueError("Nothing to annotate")
    dest = output_path(path, "Annotated")
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            for index, page_marks in marks.items():
                if page_marks:
                    page = doc[index]
                    _draw_marks_on_page(page, page_marks)
            doc.save(dest, garbage=3, deflate=True)
        return dest
    with Image.open(path) as im:
        im.load()
        return save_image(draw_marks_on_image(im, marks.get(0, [])), dest)

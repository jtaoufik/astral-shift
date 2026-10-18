"""Multi-file and page-level PDF operations: merge and split."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from .files import kind, output_path


def merge(paths: list[Path], dest: Path | None = None) -> Path:
    """Join PDFs and images, in order, into one PDF beside the first file."""
    paths = [Path(p) for p in paths]
    if len(paths) < 2:
        raise ValueError("Pick at least two files to merge")
    dest = dest or output_path(paths[0], "Merged", "pdf")
    out = pymupdf.open()
    for p in paths:
        if kind(p) == "pdf":
            with pymupdf.open(p) as src:
                out.insert_pdf(src)
        else:
            with pymupdf.open(p) as img:
                pdf_bytes = img.convert_to_pdf()
            with pymupdf.open("pdf", pdf_bytes) as src:
                out.insert_pdf(src)
    out.save(dest, garbage=3, deflate=True)
    out.close()
    return dest


def split(path: Path) -> list[Path]:
    """One PDF per page: ``Name p1.pdf``, ``Name p2.pdf``…"""
    path = Path(path)
    if kind(path) != "pdf":
        raise ValueError(f"{path.name} is not a PDF")
    outs = []
    with pymupdf.open(path) as doc:
        if doc.page_count < 2:
            raise ValueError(f"{path.name} has a single page")
        for i in range(doc.page_count):
            part = pymupdf.open()
            part.insert_pdf(doc, from_page=i, to_page=i)
            dest = output_path(path, f"p{i + 1}", "pdf")
            part.save(dest, garbage=3, deflate=True)
            part.close()
            outs.append(dest)
    return outs

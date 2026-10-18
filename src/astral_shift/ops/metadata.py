"""Read and strip metadata (PDF info + XMP, image EXIF/XMP/ICC text chunks)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import ExifTags, Image

from .files import PIL_FORMAT, kind, output_path


def read_metadata(path: Path) -> dict[str, str]:
    """Human-readable metadata, empty values left out."""
    path = Path(path)
    out: dict[str, str] = {}
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            for k, v in (doc.metadata or {}).items():
                if v:
                    out[k[0].upper() + k[1:]] = str(v)
            out["Pages"] = str(doc.page_count)
            if doc.get_xml_metadata():
                out["XMP"] = "present"
        return out
    with Image.open(path) as im:
        out["Size"] = f"{im.width} x {im.height}"
        out["Mode"] = im.mode
        exif = im.getexif()
        for tag, value in exif.items():
            name = ExifTags.TAGS.get(tag, str(tag))
            if isinstance(value, bytes):
                value = f"<{len(value)} bytes>"
            out[name] = str(value)
        for ifd_id in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
            ifd = exif.get_ifd(ifd_id)  # {} when absent
            names = ExifTags.GPSTAGS if ifd_id == ExifTags.IFD.GPSInfo else ExifTags.TAGS
            for tag, value in ifd.items():
                if isinstance(value, bytes):
                    value = f"<{len(value)} bytes>"
                out[names.get(tag, str(tag))] = str(value)
        for key in ("dpi", "Software", "Author", "Comment", "comment", "Description", "XML:com.adobe.xmp"):
            if key in im.info:
                v = im.info[key]
                out[key] = "present" if key.startswith("XML") else str(v)
    return out


def strip_metadata(path: Path) -> Path:
    path = Path(path)
    dest = output_path(path, "Clean")
    if kind(path) == "pdf":
        with pymupdf.open(path) as doc:
            doc.set_metadata({})
            doc.del_xml_metadata()
            doc.scrub(
                attached_files=False, clean_pages=False, embedded_files=False, hidden_text=False,
                javascript=True, metadata=True, redactions=False, redact_images=0,
                remove_links=False, reset_fields=False, reset_responses=False,
                thumbnails=True, xml_metadata=True,
            )
            doc.save(dest, garbage=4, deflate=True, no_new_id=True)
        return dest
    with Image.open(path) as im:
        im.load()
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)  # keep the visible orientation once EXIF is gone
        fmt = PIL_FORMAT[path.suffix.lower().lstrip(".")]
        clean = im.copy()
        clean.info = {}
        params = {"quality": 95} if fmt in ("JPEG", "WEBP") else {}
        if im.mode == "P" and "transparency" in im.info:
            params["transparency"] = im.info["transparency"]
        clean.save(dest, fmt, **params)
    return dest

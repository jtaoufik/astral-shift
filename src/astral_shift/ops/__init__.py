"""File operations. Pure functions, no Qt: the GUI and the CLI both call these."""
from .background import Background, PRESETS, RATIOS, add_background
from .compress import LEVELS, compress
from .convert import convert, default_target, first_page_image, targets_for
from .edit import Adjustments, crop, edit, rotate
from .files import UnsupportedFile, is_supported, kind, output_path
from .markup import Mark, annotate, redact
from .metadata import read_metadata, strip_metadata
from .pages import merge, split

__all__ = [
    "Adjustments", "Background", "LEVELS", "Mark", "PRESETS", "RATIOS", "UnsupportedFile",
    "add_background", "annotate", "compress", "convert", "crop", "default_target", "edit",
    "first_page_image", "is_supported", "kind", "merge", "output_path", "read_metadata", "redact",
    "rotate", "split", "strip_metadata", "targets_for",
]

"""PyInstaller entry point (the package __main__ uses relative imports)."""
import sys

from astral_shift.cli import main

sys.exit(main())

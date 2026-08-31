"""nirisplit — split your Niri WM config into multiple files."""

__version__ = "0.1.0"
__author__ = "niri-split contributors"
__license__ = "MIT"

from .merger import MERGEABLE, FileError, merge_configs, parse_segments, extract_body, validate_file

__all__ = ["MERGEABLE", "FileError", "merge_configs", "parse_segments", "extract_body", "validate_file", "__version__"]

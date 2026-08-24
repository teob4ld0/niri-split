"""nirisplit — split your Niri WM config into multiple files."""

__version__ = "0.1.0"
__author__ = "niri-split contributors"
__license__ = "MIT"

from .merger import MERGEABLE, merge_configs, parse_segments, extract_body

__all__ = ["MERGEABLE", "merge_configs", "parse_segments", "extract_body", "__version__"]

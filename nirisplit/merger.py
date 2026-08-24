"""
nirisplit.merger
~~~~~~~~~~~~~~~~
Core KDL config merging logic.

Given a directory of numbered .kdl files (e.g. conf.d/01-outputs.kdl),
merge_configs() produces a single, valid config.kdl.

Nodes whose names are in MERGEABLE have their *children* combined across all
files that contain them.  Every other node is appended to the output as-is.

Example — two files that both declare a layout block:

    # 04-layout.kdl          # 05-decoration.kdl
    layout {                 layout {
        gaps 16                  focus-ring { width 4 }
    }                        }

Merged result:

    layout {
        gaps 16
        focus-ring { width 4 }
    }
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["MERGEABLE", "merge_configs", "parse_segments", "extract_body"]

# Node names whose children are merged across files instead of duplicated.
MERGEABLE: frozenset[str] = frozenset({"layout", "binds", "animations", "input"})


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _significant_chars(line: str):
    """Yield characters in *line* that are outside strings and comments."""
    i = 0
    n = len(line)
    while i < n:
        # Line comment → rest of line is insignificant
        if line[i : i + 2] == "//":
            return
        # Block comment (simplified: single-line only for typical configs)
        if line[i : i + 2] == "/*":
            end = line.find("*/", i + 2)
            i = (end + 2) if end != -1 else n
            continue
        # Raw string  r#"..."#
        if line[i] == "r" and i + 1 < n and line[i + 1] == "#":
            j = i + 1
            while j < n and line[j] == "#":
                j += 1
            hash_count = j - i - 1
            if j < n and line[j] == '"':
                closing = '"' + "#" * hash_count
                k = line.find(closing, j + 1)
                i = (k + len(closing)) if k != -1 else n
                continue
        # Quoted string
        if line[i] == '"':
            i += 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                elif line[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        yield line[i]
        i += 1


def _node_name(lines: list[str]) -> str | None:
    """
    Return the node name for a multi-line segment, or None if the segment
    contains no node (e.g. blank lines or comments only).

    Disabled nodes (those prefixed with /-) return None so they are never
    merged — they are passed through verbatim.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Comment lines
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        # Disabled node operator — pass through unchanged
        if stripped.startswith("/-"):
            return None
        m = re.match(r"^([\w-]+)", stripped)
        return m.group(1) if m else None
    return None


def _find_block_bounds(text: str) -> tuple[int, int] | None:
    """
    Return (open_pos, close_pos) of the outermost ``{ }`` pair in *text*,
    correctly skipping braces that appear inside strings or comments.

    Returns None if no block is found.
    """
    open_pos: int | None = None
    depth = 0
    i = 0
    n = len(text)

    while i < n:
        # Line comment
        if text[i : i + 2] == "//":
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        # Block comment
        if text[i : i + 2] == "/*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        # Raw string
        if text[i] == "r" and i + 1 < n and text[i + 1] == "#":
            j = i + 1
            while j < n and text[j] == "#":
                j += 1
            h = j - i - 1
            if j < n and text[j] == '"':
                closing = '"' + "#" * h
                k = text.find(closing, j + 1)
                i = n if k == -1 else k + len(closing)
                continue
        # Quoted string
        if text[i] == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        if text[i] == "{":
            if open_pos is None:
                open_pos = i
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0 and open_pos is not None:
                return open_pos, i
        i += 1

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_body(segment_text: str) -> str:
    """
    Return the raw text between the outermost ``{`` and ``}`` of a block
    segment.  Returns an empty string for line-node segments.
    """
    bounds = _find_block_bounds(segment_text)
    if bounds is None:
        return ""
    open_pos, close_pos = bounds
    return segment_text[open_pos + 1 : close_pos]


def parse_segments(text: str) -> list[tuple[str | None, str]]:
    """
    Split *text* into a list of ``(node_name, raw_text)`` tuples where each
    tuple represents one top-level KDL item.

    *node_name* is ``None`` for blank lines, comments, and disabled nodes
    (``/-`` prefix).  Braces inside strings and comments do not affect depth
    counting.
    """
    segments: list[tuple[str | None, str]] = []
    buf: list[str] = []
    depth = 0

    for line in text.splitlines(keepends=True):
        buf.append(line)
        delta = sum(
            1 if ch == "{" else -1 if ch == "}" else 0
            for ch in _significant_chars(line)
        )
        depth += delta

        if depth <= 0:
            seg = "".join(buf)
            segments.append((_node_name(buf), seg))
            buf = []
            depth = 0  # guard against negative depth from malformed input

    if buf:
        segments.append((_node_name(buf), "".join(buf)))

    return segments


def merge_configs(conf_dir: Path) -> str:
    """
    Merge all ``*.kdl`` files in *conf_dir* (sorted by name) into a single
    KDL string suitable for use as Niri's ``config.kdl``.

    Nodes whose names are in :data:`MERGEABLE` have their children combined;
    all other nodes are appended in the order they appear across the files.
    """
    conf_dir = Path(conf_dir)
    kdl_files = sorted(conf_dir.glob("*.kdl"))
    if not kdl_files:
        raise FileNotFoundError(f"No .kdl files found in {conf_dir}")

    # merged_bodies[name] → list of body strings to join
    merged_bodies: dict[str, list[str]] = {}
    # ordered output items: either ("merge", name) or ("text", raw)
    ordered: list[tuple[str, str]] = []
    seen_merge: set[str] = set()

    for kdl_file in kdl_files:
        content = kdl_file.read_text(encoding="utf-8")
        for name, text in parse_segments(content):
            if name in MERGEABLE:
                body = extract_body(text)
                if body.strip():
                    merged_bodies.setdefault(name, []).append(body)
                if name not in seen_merge:
                    seen_merge.add(name)
                    ordered.append(("merge", name))
            else:
                ordered.append(("text", text))

    parts: list[str] = []
    emitted_merge: set[str] = set()

    for kind, data in ordered:
        if kind == "merge":
            name = data
            if name not in emitted_merge:
                emitted_merge.add(name)
                bodies = merged_bodies.get(name, [])
                combined = "".join(bodies)
                parts.append(f"{name} {{\n{combined}}}\n")
        else:
            parts.append(data)

    return "".join(parts)

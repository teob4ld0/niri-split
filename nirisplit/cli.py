"""
nirisplit.cli
~~~~~~~~~~~~~
Command-line interface for niri-split.

Usage examples
--------------
One-shot merge::

    niri-split

Custom paths::

    niri-split --conf-dir ~/.config/niri/conf.d --output ~/.config/niri/config.kdl

Watch mode (requires the ``watchdog`` package)::

    niri-split --watch
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .merger import merge_configs


_DEFAULT_CONF_DIR = Path.home() / ".config" / "niri" / "conf.d"
_DEFAULT_OUTPUT = Path.home() / ".config" / "niri" / "config.kdl"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="niri-split",
        description=(
            "Merge a directory of numbered .kdl snippets into a single "
            "Niri config.kdl.  Nodes listed in MERGEABLE (layout, binds, "
            "animations, input) have their children combined; everything else "
            "is appended in file order."
        ),
    )
    p.add_argument(
        "--conf-dir",
        metavar="DIR",
        type=Path,
        default=_DEFAULT_CONF_DIR,
        help=f"Directory containing the numbered .kdl files (default: {_DEFAULT_CONF_DIR})",
    )
    p.add_argument(
        "--output",
        metavar="FILE",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Destination config.kdl (default: {_DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--stdout",
        action="store_true",
        help="Print the merged config to stdout instead of writing a file.",
    )
    p.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Watch the conf-dir for changes and rebuild automatically. "
            "Requires the 'watchdog' package (pip install watchdog)."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return p


def _run_once(conf_dir: Path, output: Path, stdout: bool) -> bool:
    """Merge once. Returns True on success."""
    try:
        merged = merge_configs(conf_dir)
    except FileNotFoundError as exc:
        print(f"niri-split: error: {exc}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"niri-split: unexpected error: {exc}", file=sys.stderr)
        return False

    if stdout:
        print(merged, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(merged, encoding="utf-8")
        print(f"niri-split: wrote {output}")

    return True


def _watch(conf_dir: Path, output: Path) -> None:
    """Watch conf_dir and rebuild on changes (requires watchdog)."""
    try:
        from watchdog.observers import Observer  # type: ignore
        from watchdog.events import FileSystemEventHandler  # type: ignore
    except ImportError:
        print(
            "niri-split: --watch requires the 'watchdog' package.\n"
            "Install it with:  pip install watchdog",
            file=sys.stderr,
        )
        sys.exit(1)

    import threading

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._timer: threading.Timer | None = None
            self._lock = threading.Lock()

        def _schedule_rebuild(self, path: str) -> None:
            # Debounce: wait 300 ms after the last event before rebuilding
            with self._lock:
                if self._timer is not None:
                    self._timer.cancel()
                self._timer = threading.Timer(
                    0.3, self._rebuild, args=(path,)
                )
                self._timer.start()

        def _rebuild(self, path: str) -> None:
            print(f"niri-split: change detected ({path}), rebuilding…")
            _run_once(conf_dir, output, stdout=False)

        def on_modified(self, event):
            if not event.is_directory and str(event.src_path).endswith(".kdl"):
                self._schedule_rebuild(event.src_path)

        def on_created(self, event):
            if not event.is_directory and str(event.src_path).endswith(".kdl"):
                self._schedule_rebuild(event.src_path)

    observer = Observer()
    observer.schedule(_Handler(), str(conf_dir), recursive=False)
    observer.start()
    print(f"niri-split: watching {conf_dir} for changes (Ctrl+C to stop)…")

    # Initial build
    _run_once(conf_dir, output, stdout=False)

    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.watch:
        _watch(args.conf_dir, args.output)
    else:
        success = _run_once(args.conf_dir, args.output, stdout=args.stdout)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

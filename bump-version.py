#!/usr/bin/env python3
# bump-version.py
"""
bump-version.py — Bump this repository's version.

Updates the VERSION file and every `Version: x.y.z` line in the documents
listed in VERSIONED_DOCS. All updates succeed together or none are applied.

Usage:
    bump-version.py patch          0.1.0 -> 0.1.1
    bump-version.py minor          0.1.1 -> 0.2.0
    bump-version.py major          0.2.0 -> 1.0.0
    bump-version.py 0.3.2          set an explicit version
"""

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
VERSION_FILE = _HERE / "VERSION"

# Documents carrying a `Version: x.y.z` line that tracks the repo version.
VERSIONED_DOCS = [
    _HERE / "README.md",
    _HERE / "docs" / "en" / "README.md",
]

VERSION_LINE = re.compile(r"^Version:\s*(\d+\.\d+\.\d+)\s*$", re.MULTILINE)


def fail(msg: str) -> None:
    print(f"[BUMP ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def read_current() -> str:
    try:
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        fail(f"VERSION file not found at {VERSION_FILE}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        fail(f"VERSION file does not contain a semantic version: {text!r}")
    return text


def next_version(current: str, arg: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", arg):
        return arg
    major, minor, patch = (int(p) for p in current.split("."))
    if arg == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if arg == "minor":
        return f"{major}.{minor + 1}.0"
    if arg == "major":
        return f"{major + 1}.0.0"
    fail(f"Expected patch, minor, major, or an explicit x.y.z, got {arg!r}")


def check_doc(path: Path) -> None:
    """Verify a document contains exactly one matchable Version: line.

    On failure, print every line containing 'Version' so the mismatch is
    visible immediately rather than requiring a second debugging session.
    """
    if not path.exists():
        fail(f"Versioned document not found: {path}")
    text = path.read_text(encoding="utf-8")
    matches = VERSION_LINE.findall(text)
    if len(matches) == 1:
        return
    print(f"[BUMP ERROR] Expected exactly one 'Version: x.y.z' line in {path},", file=sys.stderr)
    print(f"  found {len(matches)}. Lines containing 'Version':", file=sys.stderr)
    for i, line in enumerate(text.splitlines(), start=1):
        if "Version" in line:
            print(f"    {i}: {line!r}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    current = read_current()
    new = next_version(current, sys.argv[1])

    # Validate everything before writing anything.
    for doc in VERSIONED_DOCS:
        check_doc(doc)

    VERSION_FILE.write_text(new + "\n", encoding="utf-8")
    print(f"VERSION: {current} -> {new}")
    for doc in VERSIONED_DOCS:
        text = doc.read_text(encoding="utf-8")
        doc.write_text(VERSION_LINE.sub(f"Version: {new}", text, count=1), encoding="utf-8")
        print(f"{doc.relative_to(_HERE)}: Version line -> {new}")

    print()
    print("Remember to add a changelog entry in docs/en/README.md before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

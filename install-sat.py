#!/usr/bin/env python3
# install-sat.py
"""
install-sat.py — Manage user-space installations of SAT Tools.

This manager owns the full lifecycle of SAT Tools installations:
acquisition, placement, environment creation, activation, and removal.
It installs versioned, self-contained artifacts and never touches the
tool's own runtime configuration (~/.config/sat/).

Usage:
    install-sat.py --install [VERSION]   Install a version (default: latest tag)
    install-sat.py --switch VERSION      Point the env file at an installed version
    install-sat.py --status              Show installed versions and the active one
    install-sat.py --remove VERSION      Remove an installed version
    install-sat.py --version             Show this manager's version

What this manager owns:
    ~/.local/share/sat-tool/<version>/   Installed artifacts, one per version
    ~/.local/share/sat-tool/<version>/.venv/
                                         Per-version Python environment
    ~/.config/sat-tool/sat-tool.env      Active-version pointer, sourced by wrappers
    ~/.local/bin/sat, ~/.local/bin/collection
                                         Generated wrapper scripts

What this manager does not touch:
    ~/.config/sat/                       SAT's own runtime domain (owned by sat init)

Requires: Python 3.8+, network access to github.com for --install.
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

MANAGER_NAME    = "osat-fluent-sat-tool"
UPSTREAM_REPO   = "steelcj/sat"
TARBALL_URL     = "https://github.com/{repo}/archive/refs/tags/v{version}.tar.gz"
TAGS_API_URL    = "https://api.github.com/repos/{repo}/tags"
MIN_SAT_VERSION = (0, 4, 0)  # first layout-agnostic release; older tags predate .venv

SHARE_DIR   = Path.home() / ".local" / "share" / "sat-tool"
CONFIG_DIR  = Path.home() / ".config" / "sat-tool"
ENV_FILE    = CONFIG_DIR / "sat-tool.env"
BIN_DIR     = Path.home() / ".local" / "bin"

# Tier dispatchers to expose as wrapper commands: (command, relative path in artifact)
WRAPPED_COMMANDS = [
    ("sat",        "en/bin/sat/sat"),
    ("collection", "en/bin/collection/collection"),
]

_HERE         = Path(__file__).resolve().parent
_VERSION_FILE = _HERE / "VERSION"

DIR_MODE  = 0o700  # owner-only throughout, least privilege
FILE_MODE = 0o600
EXEC_MODE = 0o700


# ── Small helpers ─────────────────────────────────────────────────────────────

def manager_version() -> str:
    """Read this manager's version from its VERSION file."""
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "unknown"


def _tilde(path: Path) -> str:
    """Replace home directory prefix with ~ for readability."""
    home = str(Path.home())
    s = str(path)
    return s.replace(home, "~", 1) if s.startswith(home) else s


def parse_version(text: str):
    """Parse 'x.y.z' into a comparable tuple. Exits on malformed input."""
    parts = text.strip().lstrip("v").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        print(f"[SAT-TOOL ERROR] Not a valid semantic version: {text!r}", file=sys.stderr)
        sys.exit(1)
    return tuple(int(p) for p in parts)


def make_owner_only(path: Path) -> None:
    """Set owner-only permissions on a directory tree."""
    if os.name == "nt":
        return  # POSIX modes are advisory on Windows; NTFS ACLs inherit from %USERPROFILE%
    for root, dirs, files in os.walk(path):
        os.chmod(root, DIR_MODE)
        for f in files:
            p = Path(root) / f
            # Never chmod through a symlink: a venv's bin/python3 links to the
            # system interpreter, which the user does not own and the manager
            # must never touch. A symlink's own mode is meaningless on Linux.
            if p.is_symlink():
                continue
            mode = EXEC_MODE if os.access(p, os.X_OK) else FILE_MODE
            os.chmod(p, mode)


# ── Version discovery ─────────────────────────────────────────────────────────

def latest_tag() -> str:
    """Return the newest upstream tag (semver order), stripped of its v prefix."""
    url = TAGS_API_URL.format(repo=UPSTREAM_REPO)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"[SAT-TOOL ERROR] Could not query upstream tags: {e}", file=sys.stderr)
        print("  Specify a version explicitly: install-sat.py --install VERSION", file=sys.stderr)
        sys.exit(1)
    versions = []
    for tag in tags:
        name = tag.get("name", "")
        parts = name.lstrip("v").split(".")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            versions.append(tuple(int(p) for p in parts))
    if not versions:
        print("[SAT-TOOL ERROR] No semantic version tags found upstream.", file=sys.stderr)
        sys.exit(1)
    return ".".join(str(n) for n in max(versions))


# ── Env file and wrappers ─────────────────────────────────────────────────────

def active_version() -> str:
    """Return the version the env file points at, or empty string if none."""
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("SAT_TOOL_ROOT="):
            root = line.split("=", 1)[1].strip().strip('"')
            return Path(root).name
    return ""


def write_env_file(version: str) -> None:
    """Write the env file pointing at the given installed version."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(CONFIG_DIR, DIR_MODE)
    root = SHARE_DIR / version
    ENV_FILE.write_text(
        f'# {_tilde(ENV_FILE)}\n'
        f'# Generated by {MANAGER_NAME}. Sourced by wrapper scripts at runtime.\n'
        f'SAT_TOOL_ROOT="{root}"\n',
        encoding="utf-8",
    )
    if os.name != "nt":
        os.chmod(ENV_FILE, FILE_MODE)


def write_wrappers() -> None:
    """Generate wrapper scripts in ~/.local/bin from the nix template."""
    template = (_HERE / "scripts" / "nix" / "wrapper.template").read_text(encoding="utf-8")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for command, dispatcher in WRAPPED_COMMANDS:
        wrapper = BIN_DIR / command
        wrapper.write_text(
            template.format(command=command, dispatcher=dispatcher,
                            manager=MANAGER_NAME, env_file=_tilde(ENV_FILE)),
            encoding="utf-8",
        )
        os.chmod(wrapper, EXEC_MODE)
        print(f"  wrapper written:  {_tilde(wrapper)}  ✓")


# ── Lifecycle: install ────────────────────────────────────────────────────────

def download_tarball(version: str, dest: Path) -> Path:
    """Download the release tarball for a version. Returns the tarball path."""
    url = TARBALL_URL.format(repo=UPSTREAM_REPO, version=version)
    tarball = dest / f"sat-{version}.tar.gz"
    print(f"  downloading:      {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tarball, "wb") as out:
            shutil.copyfileobj(resp, out)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[SAT-TOOL ERROR] No upstream tag v{version}.", file=sys.stderr)
        else:
            print(f"[SAT-TOOL ERROR] Download failed: {e}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[SAT-TOOL ERROR] Download failed: {e}", file=sys.stderr)
        sys.exit(1)
    return tarball


def extract_artifact(tarball: Path, version: str, workdir: Path) -> Path:
    """Extract the tarball, strip the top-level directory, return the tree root."""
    with tarfile.open(tarball, "r:gz") as tar:
        # Refuse entries that would escape the extraction directory.
        for member in tar.getmembers():
            target = (workdir / member.name).resolve()
            if not str(target).startswith(str(workdir.resolve())):
                print(f"[SAT-TOOL ERROR] Unsafe path in tarball: {member.name}", file=sys.stderr)
                sys.exit(1)
        tar.extractall(workdir)
    top = workdir / f"sat-{version}"
    if not top.is_dir():
        candidates = [p for p in workdir.iterdir() if p.is_dir()]
        if len(candidates) != 1:
            print("[SAT-TOOL ERROR] Unexpected tarball layout.", file=sys.stderr)
            sys.exit(1)
        top = candidates[0]
    return top


def create_venv(install_root: Path) -> None:
    """Create the per-version venv inside the artifact and install satlib."""
    venv_dir = install_root / ".venv"
    print(f"  creating venv:    {_tilde(venv_dir)}")
    result = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)])
    if result.returncode != 0:
        print("[SAT-TOOL ERROR] venv creation failed.", file=sys.stderr)
        sys.exit(1)
    pip = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "pip"
    print("  installing satlib and pinned dependencies ...")
    result = subprocess.run(
        [str(pip), "install", "--quiet", "-e", str(install_root)],
        cwd=str(install_root),
    )
    if result.returncode != 0:
        print("[SAT-TOOL ERROR] pip install failed. The partial install was kept for", file=sys.stderr)
        print(f"  inspection at {_tilde(install_root)}. Remove it with --remove.", file=sys.stderr)
        sys.exit(1)


def cmd_install(version: str) -> int:
    if not version:
        print("  resolving latest upstream tag ...")
        version = latest_tag()
    if parse_version(version) < MIN_SAT_VERSION:
        floor = ".".join(str(n) for n in MIN_SAT_VERSION)
        print(f"[SAT-TOOL ERROR] SAT Tools v{version} predates the layout-agnostic", file=sys.stderr)
        print(f"  release. This manager supports v{floor} and later.", file=sys.stderr)
        return 1
    install_root = SHARE_DIR / version
    if install_root.exists():
        print(f"[SAT-TOOL] v{version} is already installed at {_tilde(install_root)}.")
        print("  Use --switch to activate it, or --remove first to reinstall.")
        return 1

    print(f"[SAT-TOOL] Installing SAT Tools v{version}")
    with tempfile.TemporaryDirectory(prefix="sat-tool-") as tmp:
        workdir = Path(tmp)
        tarball = download_tarball(version, workdir)
        tree = extract_artifact(tarball, version, workdir)
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(SHARE_DIR, DIR_MODE)
        shutil.move(str(tree), str(install_root))
    print(f"  artifact placed:  {_tilde(install_root)}  ✓")

    create_venv(install_root)
    make_owner_only(install_root)
    write_env_file(version)
    print(f"  env file written: {_tilde(ENV_FILE)}  ✓")
    write_wrappers()

    print()
    print(f"[SAT-TOOL] SAT Tools v{version} installed and active.")
    print("  Verify with:  sat init --version")
    if not _path_has_bin_dir():
        print()
        print(f"  Note: {_tilde(BIN_DIR)} is not on your PATH. Add it with:")
        print(f'    export PATH="$HOME/.local/bin:$PATH"')
    return 0


def _path_has_bin_dir() -> bool:
    return str(BIN_DIR) in os.environ.get("PATH", "").split(os.pathsep)


# ── Lifecycle: switch, status, remove ─────────────────────────────────────────

def cmd_switch(version: str) -> int:
    install_root = SHARE_DIR / version
    if not install_root.is_dir():
        print(f"[SAT-TOOL ERROR] v{version} is not installed. Installed versions:", file=sys.stderr)
        for v in installed_versions():
            print(f"  {v}", file=sys.stderr)
        return 1
    write_env_file(version)
    write_wrappers()
    print(f"[SAT-TOOL] Active version is now v{version}.")
    return 0


def installed_versions():
    """Return installed version strings, newest first."""
    if not SHARE_DIR.is_dir():
        return []
    found = []
    for entry in SHARE_DIR.iterdir():
        parts = entry.name.split(".")
        if entry.is_dir() and len(parts) == 3 and all(p.isdigit() for p in parts):
            found.append(tuple(int(p) for p in parts))
    return [".".join(str(n) for n in v) for v in sorted(found, reverse=True)]


def cmd_status() -> int:
    active = active_version()
    versions = installed_versions()
    print(f"[SAT-TOOL] {MANAGER_NAME} {manager_version()}")
    print(f"  install root:  {_tilde(SHARE_DIR)}")
    print(f"  env file:      {_tilde(ENV_FILE)}" + ("" if ENV_FILE.exists() else "  (absent)"))
    if not versions:
        print("  installed:     none")
        return 0
    print("  installed:")
    for v in versions:
        marker = "  ← active" if v == active else ""
        print(f"    {v}{marker}")
    if active and active not in versions:
        print(f"  [WARNING] env file points at v{active}, which is not installed.")
    return 0


def cmd_remove(version: str) -> int:
    install_root = SHARE_DIR / version
    if not install_root.is_dir():
        print(f"[SAT-TOOL ERROR] v{version} is not installed.", file=sys.stderr)
        return 1
    if version == active_version():
        print(f"[SAT-TOOL ERROR] v{version} is the active version. Switch to another", file=sys.stderr)
        print("  version first, then remove this one.", file=sys.stderr)
        return 1
    shutil.rmtree(install_root)
    print(f"[SAT-TOOL] v{version} removed, including its venv.")
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="install-sat.py",
        description="Manage user-space installations of SAT Tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  install-sat.py --install          install the latest tagged release\n"
            "  install-sat.py --install 0.4.0    install a specific version\n"
            "  install-sat.py --switch 0.4.0     activate an installed version\n"
            "  install-sat.py --status           show installed and active versions\n"
            "  install-sat.py --remove 0.4.0     remove an installed version\n"
        ),
    )
    parser.add_argument("--install", nargs="?", const="", metavar="VERSION",
                        help="Install a SAT Tools version (default: latest tag).")
    parser.add_argument("--switch", metavar="VERSION",
                        help="Point the env file at an already-installed version.")
    parser.add_argument("--status", action="store_true",
                        help="Show installed versions and the active one.")
    parser.add_argument("--remove", metavar="VERSION",
                        help="Remove an installed version.")
    parser.add_argument("--version", action="store_true",
                        help="Show this manager's version and exit.")
    args = parser.parse_args()

    if args.version:
        print(f"{MANAGER_NAME} {manager_version()}")
        return 0
    if args.install is not None:
        return cmd_install(args.install)
    if args.switch:
        return cmd_switch(args.switch)
    if args.status:
        return cmd_status()
    if args.remove:
        return cmd_remove(args.remove)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

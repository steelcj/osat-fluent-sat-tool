#!/usr/bin/env python3
#
# source
#   project: osat-fluent-sat-tool
#   path: install-sat.py
#
# install-sat.py
"""
install-sat.py — Manage user-space installations of SAT Tools.

This manager owns the full lifecycle of SAT Tools installations:
acquisition, placement, environment creation, activation, and removal.
It installs versioned, self-contained artifacts and never touches the
tool's own runtime configuration (~/.config/sat/).

Usage:
    install-sat.py --install [VERSION]   Install a version (default: latest release)
    install-sat.py --switch VERSION      Point the env file at an installed version
    install-sat.py --status              Show installed versions and the active one
    install-sat.py --remove VERSION      Remove an installed version
    install-sat.py --version             Show this manager's version

What this manager owns:
    ~/.local/share/sat-tool/<version>/   Installed artifacts, one per version
    ~/.local/share/sat-tool/<version>/.venv/
                                         Per-version Python environment
    ~/.config/sat-tool/sat-tool.env      Active-version pointer, sourced by wrappers
    ~/.local/bin/sat, ~/.local/bin/collection, ~/.local/bin/content
                                         Generated wrapper scripts

What this manager does not touch:
    ~/.config/sat/                       SAT's own runtime domain (owned by sat init)

Requires: Python 3.8+. --install needs network access to api.github.com, to
read the published release, and to github.com, to download its assets.
"""

import argparse
import hashlib
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
from typing import NamedTuple

# ── Constants ─────────────────────────────────────────────────────────────────

MANAGER_NAME    = "osat-fluent-sat-tool"
UPSTREAM_REPO   = "steelcj/sat"
MIN_SAT_VERSION = (0, 4, 0)  # first layout-agnostic release; older tags predate .venv

# Acquisition is from published releases, not from tag archives. A release is
# the artifact the maintainer deliberately published: built deterministically
# by publish-release.py from `git archive`, checksummed, and attached. A tag
# archive is generated on demand by GitHub from whatever the tag points at,
# carries no checksum, and exists for every tag whether or not it was ever
# meant to be installed. Installing from releases means a cut-but-unpublished
# tag is not installable, and every download is verified before it is opened.
RELEASE_LATEST_URL = "https://api.github.com/repos/{repo}/releases/latest"
RELEASE_TAG_URL    = "https://api.github.com/repos/{repo}/releases/tags/v{version}"
RELEASES_PAGE_URL  = "https://github.com/{repo}/releases"
ASSET_NAME         = "sat-{version}.tar.gz"  # as built by publish-release.py
CHECKSUM_ASSET     = "SHA256SUMS"

# GitHub's API answers unauthenticated requests but wants a User-Agent.
USER_AGENT = f"{MANAGER_NAME}/{{version}} (+https://github.com/{UPSTREAM_REPO})"

SHARE_DIR   = Path.home() / ".local" / "share" / "sat-tool"
CONFIG_DIR  = Path.home() / ".config" / "sat-tool"
ENV_FILE    = CONFIG_DIR / "sat-tool.env"
BIN_DIR     = Path.home() / ".local" / "bin"


class Tier(NamedTuple):
    """A tier dispatcher exposed as a wrapper command."""
    command:    str    # the name written into ~/.local/bin
    dispatcher: str    # path to the dispatcher inside the artifact
    python:     bool   # launch with the venv interpreter rather than a shebang
    since:      tuple  # first SAT Tools version whose artifact ships it


# The tiers this manager wraps. `python` is set for a dispatcher that is a
# Python file: its own `#!/usr/bin/env python3` shebang would resolve the
# system interpreter, which carries neither satlib nor the runtime
# dependencies, so the wrapper launches it with the per-version venv python.
# `since` records when a dispatcher entered the artifact, so installing an
# older supported version omits that command instead of failing over it.
TIERS = [
    Tier("sat",        "en/bin/sat/sat",               False, (0, 4, 0)),
    Tier("collection", "en/bin/collection/collection", False, (0, 4, 0)),
    Tier("content",    "en/bin/content/content.py",    True,  (0, 7, 4)),
]

VENV_PYTHON = ".venv/bin/python3"

# Present in every wrapper this manager writes; the marker that makes a file in
# ~/.local/bin safe to remove when a tier is absent from the target version.
WRAPPER_MARKER = "path: scripts/nix/wrapper.template"

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


# ── Upstream releases ─────────────────────────────────────────────────────────

def _request(url: str) -> urllib.request.Request:
    """Build a request carrying this manager's User-Agent."""
    return urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT.format(version=manager_version())}
    )


def _get_release(url: str, description: str) -> dict:
    """Fetch and decode a release document from the GitHub API."""
    try:
        with urllib.request.urlopen(_request(url), timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[SAT-TOOL ERROR] No published release for {description}.", file=sys.stderr)
            print(f"  Published releases: {RELEASES_PAGE_URL.format(repo=UPSTREAM_REPO)}",
                  file=sys.stderr)
        else:
            print(f"[SAT-TOOL ERROR] Could not query {description}: {e}", file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"[SAT-TOOL ERROR] Could not query {description}: {e}", file=sys.stderr)
        print("  Specify a version explicitly: install-sat.py --install VERSION", file=sys.stderr)
        sys.exit(1)


def latest_release() -> str:
    """Return the version of the latest published release, without its v prefix.

    This is GitHub's own latest pointer, which excludes drafts and prereleases,
    so it tracks what the maintainer published rather than the highest tag that
    happens to exist."""
    release = _get_release(RELEASE_LATEST_URL.format(repo=UPSTREAM_REPO),
                           "the latest release")
    tag = release.get("tag_name", "")
    if not tag:
        print("[SAT-TOOL ERROR] The latest release carries no tag name.", file=sys.stderr)
        sys.exit(1)
    return tag.lstrip("v")


def release_assets(version: str) -> dict:
    """Return {asset name: download URL} for a version's published release."""
    release = _get_release(RELEASE_TAG_URL.format(repo=UPSTREAM_REPO, version=version),
                           f"SAT Tools v{version}")
    return {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}


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


def tiers_present(install_root: Path):
    """The tiers whose dispatcher this artifact actually carries."""
    return [t for t in TIERS if (install_root / t.dispatcher).is_file()]


def verify_dispatchers(install_root: Path, version: str) -> None:
    """Every tier the requested version is expected to ship must be present. A
    missing one means the artifact is partial or the manager's tier list has
    drifted from the tools it installs; either way, do not write a wrapper that
    resolves to nothing. Tiers that postdate the version are simply not
    wrapped, which is how older supported releases install cleanly."""
    requested = parse_version(version)
    expected = [t for t in TIERS if requested >= t.since]
    missing = [t for t in expected if not (install_root / t.dispatcher).is_file()]
    if missing:
        print("[SAT-TOOL ERROR] The artifact is missing tier dispatchers that", file=sys.stderr)
        print(f"  v{version} is expected to ship:", file=sys.stderr)
        for t in missing:
            print(f"    {t.dispatcher}", file=sys.stderr)
        print("  Refusing to activate a partial artifact; removing it.", file=sys.stderr)
        shutil.rmtree(install_root, ignore_errors=True)
        sys.exit(1)
    names = ", ".join(t.command for t in expected)
    print(f"  dispatchers verified: {names}  ✓")


def _remove_stale_wrapper(command: str) -> None:
    """Remove a wrapper for a tier the target version does not carry, so no
    command in ~/.local/bin points at a dispatcher that is not there. Only
    files this manager wrote are removed; anything else is left alone."""
    wrapper = BIN_DIR / command
    if not wrapper.is_file():
        return
    try:
        written_by_us = WRAPPER_MARKER in wrapper.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        written_by_us = False
    if written_by_us:
        wrapper.unlink()
        print(f"  wrapper removed:  {_tilde(wrapper)}  (not in this version)")
    else:
        print(f"  [WARNING] {_tilde(wrapper)} was not written by this manager; left in place.")


def write_wrappers(install_root: Path) -> None:
    """Generate wrapper scripts in ~/.local/bin from the nix template, one per
    tier the artifact carries."""
    template = (_HERE / "scripts" / "nix" / "wrapper.template").read_text(encoding="utf-8")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    present = tiers_present(install_root)
    for tier in TIERS:
        if tier not in present:
            _remove_stale_wrapper(tier.command)
            continue
        command, dispatcher = tier.command, tier.dispatcher
        wrapper = BIN_DIR / command
        launcher = f'"$SAT_TOOL_ROOT/{VENV_PYTHON}" ' if tier.python else ""
        rendered = template.format(command=command, dispatcher=dispatcher,
                                   launcher=launcher,
                                   manager=MANAGER_NAME, env_file=_tilde(ENV_FILE))
        # Convention: the template declares `generates`; the written wrapper
        # records `generated`, concrete values only, stamped with its maker.
        rendered = rendered.replace(
            "# generates\n",
            "# generated\n",
            1,
        ).replace(
            f"#   path: ~/.local/bin/{command}\n",
            f"#   path: ~/.local/bin/{command}\n#   by: install-sat.py --install\n",
            1,
        )
        wrapper.write_text(rendered, encoding="utf-8")
        os.chmod(wrapper, EXEC_MODE)
        print(f"  wrapper written:  {_tilde(wrapper)}  ✓")


# ── Lifecycle: install ────────────────────────────────────────────────────────

def _download(url: str, dest: Path, label: str) -> Path:
    """Download a URL to a path. Exits with a readable message on failure."""
    print(f"  downloading:      {url}")
    try:
        with urllib.request.urlopen(_request(url), timeout=120) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
    except (urllib.error.URLError, OSError) as e:
        print(f"[SAT-TOOL ERROR] Download of the {label} failed: {e}", file=sys.stderr)
        sys.exit(1)
    return dest


def verify_checksum(tarball: Path, sums_file: Path, asset: str) -> None:
    """Check the downloaded tarball against the release's SHA256SUMS. A release
    publishes the digest its determinism gate produced; a download that does not
    match it is not that artifact, so refuse it rather than unpack it."""
    expected = ""
    for line in sums_file.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset:
            expected = parts[0]
            break
    if not expected:
        print(f"[SAT-TOOL ERROR] {CHECKSUM_ASSET} carries no entry for {asset}.", file=sys.stderr)
        print("  Refusing to install an artifact with no published digest.", file=sys.stderr)
        sys.exit(1)
    digest = hashlib.sha256()
    with open(tarball, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        print("[SAT-TOOL ERROR] Checksum mismatch. The download does not match the", file=sys.stderr)
        print(f"  digest published with the release.", file=sys.stderr)
        print(f"    expected: {expected}", file=sys.stderr)
        print(f"    actual:   {actual}", file=sys.stderr)
        print("  Refusing to install it.", file=sys.stderr)
        sys.exit(1)
    print(f"  checksum verified: sha256 {actual[:16]}...  ✓")


def download_release(version: str, dest: Path) -> Path:
    """Download a version's published release tarball and verify it against the
    release's SHA256SUMS. Returns the verified tarball path."""
    assets = release_assets(version)
    asset = ASSET_NAME.format(version=version)
    if asset not in assets:
        # Tolerate a differently named tarball as long as it is unambiguous:
        # the asset naming is publish-release.py's convention, not a contract
        # the installer should break over.
        tarballs = [n for n in assets if n.endswith(".tar.gz")]
        if len(tarballs) != 1:
            print(f"[SAT-TOOL ERROR] The v{version} release publishes no tarball this", file=sys.stderr)
            print(f"  manager can identify. Assets: {', '.join(assets) or 'none'}", file=sys.stderr)
            sys.exit(1)
        asset = tarballs[0]
    if CHECKSUM_ASSET not in assets:
        print(f"[SAT-TOOL ERROR] The v{version} release publishes no {CHECKSUM_ASSET}.", file=sys.stderr)
        print("  Refusing to install an artifact that cannot be verified.", file=sys.stderr)
        sys.exit(1)

    tarball = _download(assets[asset], dest / asset, "release tarball")
    sums = _download(assets[CHECKSUM_ASSET], dest / CHECKSUM_ASSET, CHECKSUM_ASSET)
    verify_checksum(tarball, sums, asset)
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


def verify_declared_version(install_root: Path, requested: str) -> None:
    """Declared-versus-actual tripwire: the artifact's VERSION must equal the
    requested tag. A mismatch means the tag was cut before its version bump;
    refuse to activate a mislabelled artifact."""
    version_file = install_root / "VERSION"
    try:
        declared = version_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print("[SAT-TOOL ERROR] The artifact carries no VERSION file. Refusing to", file=sys.stderr)
        print("  activate an unversioned artifact; removing it.", file=sys.stderr)
        shutil.rmtree(install_root, ignore_errors=True)
        sys.exit(1)
    if declared != requested:
        print(f"[SAT-TOOL ERROR] Requested v{requested} but the artifact declares", file=sys.stderr)
        print(f"  v{declared}. The tag was likely cut before its version bump.", file=sys.stderr)
        print("  Refusing to activate a mislabelled artifact; removing it.", file=sys.stderr)
        shutil.rmtree(install_root, ignore_errors=True)
        sys.exit(1)
    print(f"  version verified: artifact declares v{declared}  \u2713")


def create_venv(install_root: Path) -> None:
    """Create the per-version venv inside the artifact and install satlib."""
    venv_dir = install_root / ".venv"
    print(f"  creating venv:    {_tilde(venv_dir)}")
    result = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)])
    if result.returncode != 0:
        print("[SAT-TOOL ERROR] venv creation failed.", file=sys.stderr)
        sys.exit(1)
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    pip = bin_dir / "pip"
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    # Install the runtime dependency ledger. requirements.txt is composition
    # only: it pulls each component's co-located <component>.requirements.txt,
    # and satlib's line selects the package plus the extras the tools need
    # (e.g. mdformat for ADR-030 content-ingress normalization). Run from the
    # artifact root so the ledger's relative paths (./en/lib/satlib) resolve.
    print("  installing runtime dependencies from requirements.txt ...")
    result = subprocess.run(
        [str(pip), "install", "--quiet", "-r", "requirements.txt"],
        cwd=str(install_root),
    )
    if result.returncode != 0:
        print("[SAT-TOOL ERROR] pip install failed. The partial install was kept for", file=sys.stderr)
        print(f"  inspection at {_tilde(install_root)}. Remove it with --remove.", file=sys.stderr)
        sys.exit(1)
    # No claim without a verification behind it: prove the venv can actually
    # run the tools, not merely import the library. mdformat is required for
    # content ingress, so a venv that cannot import it cannot ingress.
    result = subprocess.run(
        [str(python), "-c", "import satlib, mdformat"],
        capture_output=True,
    )
    if result.returncode != 0:
        print("[SAT-TOOL ERROR] the runtime venv is incomplete (satlib or a", file=sys.stderr)
        print("  required dependency such as mdformat does not import). Refusing", file=sys.stderr)
        print("  to activate a broken artifact; removing it.", file=sys.stderr)
        shutil.rmtree(install_root, ignore_errors=True)
        sys.exit(1)
    print("  runtime venv verified (satlib, mdformat)  \u2713")


def cmd_install(version: str) -> int:
    if not version:
        print("  resolving latest upstream release ...")
        version = latest_release()
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
        tarball = download_release(version, workdir)
        tree = extract_artifact(tarball, version, workdir)
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(SHARE_DIR, DIR_MODE)
        shutil.move(str(tree), str(install_root))
    print(f"  artifact placed:  {_tilde(install_root)}  ✓")

    verify_declared_version(install_root, version)
    verify_dispatchers(install_root, version)
    create_venv(install_root)
    make_owner_only(install_root)
    write_env_file(version)
    print(f"  env file written: {_tilde(ENV_FILE)}  ✓")
    write_wrappers(install_root)

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
    write_wrappers(install_root)
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
    # Progress goes to stdout and refusals to stderr. Without line buffering the
    # two interleave out of order the moment either is redirected, which makes a
    # failure report read as though it happened before the step it followed.
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(
        prog="install-sat.py",
        description="Manage user-space installations of SAT Tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  install-sat.py --install          install the latest published release\n"
            "  install-sat.py --install 0.4.0    install a specific version\n"
            "  install-sat.py --switch 0.4.0     activate an installed version\n"
            "  install-sat.py --status           show installed and active versions\n"
            "  install-sat.py --remove 0.4.0     remove an installed version\n"
        ),
    )
    parser.add_argument("--install", nargs="?", const="", metavar="VERSION",
                        help="Install a SAT Tools version (default: latest release).")
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
    try:
        sys.exit(main())
    except BrokenPipeError:
        # A reader closed the pipe early, as `--status | head` does. With line
        # buffering that surfaces mid-write rather than at shutdown, so retire
        # stdout to devnull to keep the interpreter's final flush from
        # reporting it a second time, and exit as a piped-to-death tool does.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(141)

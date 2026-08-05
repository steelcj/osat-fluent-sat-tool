# osat-fluent-sat-tool

Version: 0.2.0
Status: Draft
Style Guide: style-guide--technical-documentation-for-technologists v0.2.0

## Abstract

This document describes `osat-fluent-sat-tool`, the OSAT Fluent manager for [SAT Tools](https://github.com/steelcj/sat). Unlike the self-contained binary tools in the collection (Archetype 5), SAT Tools is a versioned source tree with a managed Python runtime. This manager is the first implementation of that pattern, and this document records the layout, the lifecycle, and the rationale, pending the pattern's promotion into the governance specification.

## What this manager does

`install-sat.py` owns the full installation lifecycle of SAT Tools. In prose and comments it is a manager, not an installer, because installation is only its first act: it also activates, switches, inspects, and removes versions.

The lifecycle for one version is: download the release tarball for an upstream tag, verify the archive extracts safely, place the tree at `~/.local/share/sat-tool/<version>/`, create a Python virtual environment at `.venv/` inside that tree, install `satlib` and its pinned dependencies into it, write the env file, and generate wrapper scripts.

## Filesystem layout

```text
~/.local/share/sat-tool/
  0.4.0/                    installed artifact: en/, satlib/, VERSION, ...
    .venv/                  per-version Python environment
  0.5.0/                    versions sit side by side

~/.config/sat-tool/
  sat-tool.env              SAT_TOOL_ROOT="$HOME/.local/share/sat-tool/0.4.0"

~/.local/bin/
  sat                       generated wrapper for the sat tier dispatcher
  collection                generated wrapper for the collection tier dispatcher
  content                   generated wrapper for the content tier dispatcher
```

All manager-owned directories and files are owner-only (`0700` directories and executables, `0600` files), following the least-privilege rule used throughout the OSAT Fluent collection.

The tool's own runtime domain, `~/.config/sat/`, is never touched by this manager. It is owned by `sat init`. The two domains are distinguished by the management identifier: anything named `sat-tool` belongs to the manager, anything named `sat` belongs to the tool. This generalizes the config-collision rule of the specification's management identifier section (10.8, landing in the v0.3.0 spec bump recorded in the osat-fluent ROADMAP) into a uniform ownership convention across the config, share, and state domains, and the `-tool` identifier doubles as a provenance marker: a directory bearing it is a managed, versioned, switchable, removable unit.

## Wrappers and the env file

Wrappers are generated from `scripts/nix/wrapper.template` on every `--install` and `--switch`. Each wrapper sources the env file at runtime and executes the tier dispatcher inside the active artifact:

```bash
. "$HOME/.config/sat-tool/sat-tool.env"
exec "$SAT_TOOL_ROOT/en/bin/sat/sat" "$@"
```

Because resolution happens at runtime rather than at shell startup, switching versions is a one-line change to the env file with no shell restart, and non-interactive contexts such as systemd timers resolve the same version an interactive shell does. This is the standard OSAT Fluent wrapper contract.

A tier whose dispatcher is a Python file is launched with the per-version venv interpreter rather than through its own shebang, because `#!/usr/bin/env python3` resolves the system interpreter, which carries neither `satlib` nor the runtime dependencies:

```bash
. "$HOME/.config/sat-tool/sat-tool.env"
exec "$SAT_TOOL_ROOT/.venv/bin/python3" "$SAT_TOOL_ROOT/en/bin/content/content.py" "$@"
```

A wrapper is written for every tier the installed artifact carries, and each tier records the version that first ships its dispatcher. `content` enters at SAT Tools v0.7.4, so installing an earlier supported version omits that command rather than failing over it, and switching back to an earlier version removes the wrapper instead of leaving a command pointing at a dispatcher that is not there.

## Why this is not Archetype 5

Archetype 5 covers self-contained binaries acquired from upstream releases, where the manager's job is acquire, verify, place, and wrap. SAT Tools is a source tree whose scripts import `satlib`, read `VERSION` at the tree root, and execute through a Python environment. The artifact is therefore the tree plus a managed runtime, and the lifecycle gains two steps Archetype 5 does not have: environment creation and dependency installation. We record this here as a candidate archetype, a versioned source tree with managed runtime, to be written into the governance specification once this implementation has proven it.

Keeping the venv inside the versioned tree was a deliberate choice over a shared environment. It makes each installed version self-contained and relocatable, removal atomic (deleting a version deletes its environment), and side-by-side versions genuinely independent. The alternative, a shared venv keyed by version outside the tree, was the pre-0.4.0 SAT layout, and it doubled the version bookkeeping while breaking relocatability. SAT Tools v0.4.0 changed its dispatchers to expect `$SAT_ROOT/.venv` for exactly this reason, which is why v0.4.0 is this manager's minimum supported version.

Acquisition is from a published GitHub release rather than by `git clone` or from a tag archive. A release is the artifact the maintainer deliberately published: `publish-release.py` builds it from `git archive`, refuses on any byte difference between two builds, computes `SHA256SUMS`, and attaches both. The installer downloads that tarball with its checksum file and verifies the digest before unpacking, so the artifact is pinned and verified in fact rather than in principle. A tag archive would offer none of this: GitHub generates it on demand, publishes no digest for it, and produces one for every tag whether or not the tag was ever meant to be installed. Development clones remain untouched by the manager and live wherever development lives. The same artifact is intended to have three habitats: the development clone, the XDG installation this manager owns, and a future embedded copy placed inside an archive by the birthing process. The dispatchers' relative root resolution supports all three.

## Usage

```bash
python3 install-sat.py --install          # install the latest published release
python3 install-sat.py --install 0.4.0    # install a specific version
python3 install-sat.py --switch 0.4.0     # activate an installed version
python3 install-sat.py --status           # show installed and active versions
python3 install-sat.py --remove 0.4.0     # remove a non-active version
python3 install-sat.py --version          # show this manager's version
```

`--install` refuses versions below 0.4.0, refuses a version with no published release, refuses a download whose digest does not match the release's `SHA256SUMS`, refuses an artifact missing a tier dispatcher its version is expected to ship, refuses to overwrite an existing installation, and warns when `~/.local/bin` is not on `PATH`. `--remove` refuses to remove the active version; switch first. If a `pip install` fails partway, the partial tree is kept for inspection and can be cleaned up with `--remove`.

## Requirements

Python 3.8 or later with the `venv` module, and network access for `--install` to `api.github.com`, to read the release, and to `github.com`, to download its assets. The manager itself uses only the Python standard library.

## Windows status

Windows is a first-class target of the OSAT Fluent collection, and the manager's placement, environment, and env file logic are written to run on Windows. The current blocker is upstream: the `sat` and `collection` tier dispatchers (`en/bin/sat/sat`, `en/bin/collection/collection`) are bash scripts, so generated Windows wrappers have nothing native to execute. The `content` tier is the exception and the precedent: `en/bin/content/content.py` is a Python dispatcher, which this manager already launches with the venv interpreter rather than through a shebang, and that is exactly the form a Windows wrapper can execute. `scripts/windows/README.md` records the gap and the candidate resolutions. Windows wrapper generation lands when the remaining tiers follow that precedent, when SAT ships Windows dispatchers, or when the wrapper-direct approach is adopted.

## License

This document, *osat-fluent-sat-tool*, by **Christopher Steel**, with AI assistance from **Claude (Anthropic)**, is licensed under the [GNU General Public License v3.0 or later](https://www.gnu.org/licenses/gpl-3.0.html).

## Changelog

| Version | Status | Notes |
|---------|--------|-------|
| 0.1.1 | Draft | make_owner_only skips symlinks; chmod through a venv's interpreter symlink hit EPERM on the system Python |
| 0.1.0 | Draft | Initial scaffold: manager with install, switch, status, remove lifecycle, nix wrapper template, validated against SAT Tools v0.4.0 |

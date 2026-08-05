# Changelog

All notable changes to osat-fluent-sat-tool are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions track the `VERSIO
N` file and the git tags. Dates are ISO 8601.

## [Unreleased]

### Added

- `content` tier wrapper. The installer provisioned the content tier's runtime dependency (mdformat, for ADR-030 ingress normalization) but never wrote a `content` command, so the tier was installed and unreachable. Wrappers are now written for every tier the artifact carries.
- Dispatcher verification at install time. A version that is expected to ship a tier but does not is refused and removed, rather than activated with a wrapper that resolves to nothing.
- Stale wrapper removal on `--switch`. Switching to a version that predates a tier removes that command from `~/.local/bin` instead of leaving it pointing at an absent dispatcher. Only wrappers this manager wrote are removed.

- Checksum verification. The release's `SHA256SUMS` is downloaded alongside the tarball and the digest is checked before anything is unpacked. A mismatch, or an asset with no published digest, is refused.

### Changed

- Acquisition is from published releases, not tag archives. `--install` reads the release for the requested version and downloads the tarball `publish-release.py` built and attached; `--install` with no version resolves GitHub's latest release pointer, which excludes drafts and prereleases, rather than the highest tag that happens to exist. A version with no published release is refused with a pointer to the releases page. For v0.8.0 the two sources carry identical trees, so this changes provenance and verification, not content.
- The wrapper template takes a launcher. A tier whose dispatcher is a Python file (`content.py`) is launched with the per-version venv interpreter, because its `#!/usr/bin/env python3` shebang resolves the system python3, which carries neither satlib nor the runtime dependencies.

## [0.3.0] - 2026-08-03

### Added

- File Fairy payload

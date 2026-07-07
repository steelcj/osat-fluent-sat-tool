# Windows wrapper status

Version: 0.1.0
Status: Draft

The manager's placement, venv creation, and env file logic run on Windows, but generated Windows wrappers have nothing native to execute: the SAT tier dispatchers (`en/bin/sat/sat`, `en/bin/collection/collection`) are bash scripts.

Two candidate resolutions, to be decided with upstream:

1. SAT Tools ships PowerShell dispatchers alongside the bash ones, mirroring the existing `scripts/windows-11/` precedent for tool scripts. The manager then generates thin `.cmd` wrappers exactly as it generates the nix ones.
2. Wrapper-direct: the generated Windows wrapper reads the env file itself and invokes `%SAT_TOOL_ROOT%\.venv\Scripts\python.exe` against the tier's entry script directly, bypassing the bash dispatcher. Less duplication upstream, but dispatcher routing logic would live in two places.

Option 1 keeps one source of truth for routing and is the current lean. Recorded here so the decision is traceable when Windows validation begins.

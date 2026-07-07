# osat-fluent-sat-tool

Version: 0.1.0
Status: Draft

A user-space manager for [SAT Tools](https://github.com/steelcj/sat) installations, part of the OS Sovereign Autonomous Tools (OSAT) Fluent collection.

This manager installs versioned, self-contained SAT Tools artifacts to `~/.local/share/sat-tool/<version>/`, each with its own Python environment, activated through a single env file and generated wrapper scripts. Full documentation lives in [docs/en/README.md](docs/en/README.md).

## Quick start

```bash
python3 install-sat.py --install
sat init --version
```

## License

This software, *osat-fluent-sat-tool*, by **Christopher Steel**, is licensed under the [GNU General Public License v3.0 or later (GPL-3.0-or-later)](https://www.gnu.org/licenses/gpl-3.0.html).

You may redistribute and/or modify this software under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

See the `LICENSE` file included with this project for the full license text.

[![License: GPL v3+](https://img.shields.io/badge/License-GPLv3%2B-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

# SAT TODO

```bash
 python3 install-sat.py --remove 0.4.3
[SAT-TOOL ERROR] v0.4.3 is not installed.
initial@flow:~/2-areas/development/fluent/osat-fluent-sat-tool$ python3 install-sat.py --remove 0.4.6
[SAT-TOOL ERROR] v0.4.6 is the active version. Switch to another
  version first, then remove this one.
initial@flow:~/2-areas/development/fluent/osat-fluent-sat-tool$ python3 install-sat.py --switch 0.4.1
[SAT-TOOL ERROR] v0.4.1 is not installed. Installed versions:
  0.4.6
  0.4.5
  0.4.4
  0.4.0
initial@flow:~/2-areas/development/fluent/osat-fluent-sat-tool$ python3 install-sat.py --switch 0.4.0
  wrapper written:  ~/.local/bin/sat  ✓
  wrapper written:  ~/.local/bin/collection  ✓
[SAT-TOOL] Active version is now v0.4.0.
initial@flow:~/2-areas/development/fluent/osat-fluent-sat-tool$ python3 install-sat.py --remove 0.4.6
[SAT-TOOL] v0.4.6 removed, including its venv.
initial@flow:~/2-areas/development/fluent/osat-fluent-sat-tool$ python3 install-sat.py --install 0.4.3
[SAT-TOOL] Installing SAT Tools v0.4.3
  downloading:      https://github.com/steelcj/sat/archive/refs/tags/v0.4.3.tar.gz
  artifact placed:  ~/.local/share/sat-tool/0.4.3  ✓
[SAT-TOOL ERROR] Requested v0.4.3 but the artifact declares
  v0.4.2. The tag was likely cut before its version bump.
  Refusing to activate a mislabelled artifact; removing it.
initial@flow:~/2-areas/development/fluent/osat-fluent-sat-tool$ python3 install-sat.py --install 0.4.6
[SAT-TOOL] Installing SAT Tools v0.4.6
  downloading:      https://github.com/steelcj/sat/archive/refs/tags/v0.4.6.tar.gz
  artifact placed:  ~/.local/share/sat-tool/0.4.6  ✓
  version verified: artifact declares v0.4.6  ✓
  creating venv:    ~/.local/share/sat-tool/0.4.6/.venv
  installing satlib and pinned dependencies ...
  satlib import verified  ✓
  env file written: ~/.config/sat-tool/sat-tool.env  ✓
  wrapper written:  ~/.local/bin/sat  ✓
  wrapper written:  ~/.local/bin/collection  ✓

[SAT-TOOL] SAT Tools v0.4.6 installed and active.
  Verify with:  sat init --version

```

We need a sat list command to list all the (installed? and avaialble(?) versions


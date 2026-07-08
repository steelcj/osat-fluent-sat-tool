# Commit and versioning workflow

Version: 0.1.0
Status: Draft

## Initial Commit

```bash
git init
git status
git add .
git status
git commit
git push -u origin main
git tag -a v0.1.0 -m "version 0.1.0"
git push origin v0.1.0
```

## Version Bumps

an existing tag means `v0.1.0` already shipped, so the symlink fix is exactly the case the typology was built for: a work commit followed by a repo-scope patch bump, two commits, kept pure.

### Work Commit

```bash
# work commit: the fix only
git add .
git status
git commit -m ' modified:   install-sat.py
git push
```

Subject along the lines of `make_owner_only: skip symlinks`, status output as the body. 

### Then version bump

Then the bump:

bash

```bash
python3 bump-version.py patch
```

Output example:

```bash
VERSION: 0.1.0 -> 0.1.1
README.md: Version line -> 0.1.1
docs/en/README.md: Version line -> 0.1.1

Remember to add a changelog entry in docs/en/README.md before committing.
```

That takes `VERSION` to `0.1.1` and updates both `Version:` lines. Add the changelog row in `docs/en/README.md`, something like:

markdown

```markdown
| 0.1.1 | Draft | make_owner_only skips symlinks; chmod through a venv's interpreter symlink hit EPERM on the system Python |
```

Then:

```bash
git add .
git status
git commit -m ' modified:   README.md
        modified:   VERSION
        modified:   docs/en/README.md
'
git tag -a v0.1.1 -m "version 0.1.1"
git push
git push origin v0.1.1
```

One check before the work commit, since the tag predates the fix: `git status` right now should show `install-sat.py` as modified. If it shows *clean*, then the fix isn't in this working copy and v0.1.0 was tagged without it, in which case grep for `is_symlink` and apply the patch first. And a small historical note this creates: the `v0.1.0` tag points at a manager with the chmod bug, which is fine and normal, tags are history, not endorsements, and the changelog row is what tells future-you why `0.1.1` exists.

## Committing

```bash
git add .
git status
```

Reuse the `git status` output directly in the commit body rather than paraphrasing:

```bash
git commit
```

First push of the branch:

```bash
git push -u origin main
```

Subsequent pushes:

```bash
git push
```

## Versioning

```bash
python3 bump-version.py patch|minor|major
```

Add a changelog entry in `docs/en/README.md`, commit, then tag. Tag pushes are one-time acts per version:

```bash
git tag -a v0.1.1 -m "version 0.1.1"
git push origin v0.1.1
```

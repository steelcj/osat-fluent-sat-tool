# Commit and versioning workflow

Version: 0.1.0
Status: Draft

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

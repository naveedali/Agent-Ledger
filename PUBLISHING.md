# Publishing Agent Ledger to PyPI

The package is `agent-ledger-cli` (the name `agent-ledger` belongs to an unrelated project). It installs one command: `agent-ledger`.

The version lives in one place: `__version__` in `ledger.py`.

## Trusted publishing (recommended, one-time setup)

No API tokens to store. GitHub Actions publishes when you create a release.

1. Sign in at [pypi.org](https://pypi.org) and open **Your account → Publishing**.
2. Under **Add a new pending publisher**, fill in:
   - PyPI project name: `agent-ledger-cli`
   - Owner: `naveedali`
   - Repository name: `Agent-Ledger`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. On GitHub, open the repo's **Settings → Environments** and create an environment named `pypi`.

## Releasing a version

1. Bump `__version__` in `ledger.py` (for example `0.3.0` → `0.3.1`) and merge it to `main`.
2. On GitHub, open **Releases → Draft a new release**, create the tag `v0.3.1` (it must match `__version__`), add notes, and click **Publish release**.
3. The **Publish to PyPI** workflow builds and uploads it. A minute later:

```bash
pipx install agent-ledger-cli     # first install
pipx upgrade agent-ledger-cli     # later versions
agent-ledger update               # refresh your installed ledgers
```

## Building by hand (optional)

```bash
python3 -m pip install --upgrade build twine
python3 -m build                 # creates dist/*.whl and dist/*.tar.gz
python3 -m twine check dist/*
python3 -m twine upload dist/*   # asks for a PyPI API token
```

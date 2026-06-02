# PyPI release

GitHub Actions publishes on **Release published** when `PYPI_TOKEN` is set.

## One-time setup

1. Create a PyPI API token at https://pypi.org/manage/account/token/ (scope: project `nulm` or entire account).
2. In GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `PYPI_TOKEN`
   - Value: `pypi-...`
3. Re-run the failed **Release** workflow or publish a new GitHub release for tag `v0.1.10`.

## Manual upload (fallback)

```bash
python3 -m pip install build twine
rm -rf dist/
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

Use `__token__` as username and the API token as password.

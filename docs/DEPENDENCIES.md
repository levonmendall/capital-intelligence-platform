# Dependency management

## Runtime dependencies

`requirements.txt` defines the supported direct runtime ranges. The application,
container image, validation workflow, and security audit install from
`requirements.lock`, which contains exact versions and SHA-256 hashes compiled
for Python 3.11.

Install the production environment with:

```bash
python -m pip install --require-hashes -r requirements.lock
```

Do not add test, lint, formatting, audit, or lock-generation tools to
`requirements.txt`. Development-only tools belong in `requirements-dev.txt`.

## Development dependencies

```bash
python -m pip install --require-hashes -r requirements.lock
python -m pip install -r requirements-dev.txt
```

## Updating the lock

After intentionally changing `requirements.txt`, regenerate the lock with
Python 3.11:

```bash
python -m pip install -r requirements-dev.txt
pip-compile \
  --generate-hashes \
  --resolver=backtracking \
  --strip-extras \
  --output-file requirements.lock \
  requirements.txt
python scripts/verify_requirements_lock.py
```

Commit `requirements.txt` and `requirements.lock` together. CI rejects a lock
that omits a direct runtime dependency, lacks exact pins or SHA-256 hashes, or
contains a direct pin outside its declared source range.

## Supported Python line

The validated runtime remains Python 3.11. Python and NumPy upgrades that require
a newer interpreter must update the runtime image, CI matrix, dependency lock,
and compatibility tests in one coordinated pull request.

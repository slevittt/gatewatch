# Releasing to PyPI

A version number on PyPI can be uploaded **once and never replaced**. Before the first upload, make sure
`pyproject.toml` has the final description, the real repository URL under `[project.urls]` and your name
under `authors`, then bump `version` for every later release.

## Option A: no tokens (recommended)

1. Create the GitHub repository and push this project.
2. On pypi.org: create an account and turn on two-factor authentication.
3. PyPI, *Your account*, *Publishing*, *Add a new pending publisher*: project name `gatewatch`, your GitHub
   user and repository, workflow `publish.yml`, environment `pypi`.
4. On GitHub: *Releases*, *Draft a new release*, tag `v0.1.0`, *Publish release*. The workflow builds and uploads.

The name is yours once the first upload succeeds.

## Option B: by hand with a token

```bash
python3 -m venv /tmp/rel && /tmp/rel/bin/pip install build twine
/tmp/rel/bin/python -m build
/tmp/rel/bin/twine check dist/*
/tmp/rel/bin/twine upload dist/*      # username: __token__, password: a PyPI API token
```

Create the token at pypi.org under *Account settings*, *API tokens*. For the first upload it has to be
account-wide; after that, replace it with one limited to the `gatewatch` project. Never paste a token into
a chat, an issue or a commit.

## Check first

`pip install --index-url https://test.pypi.org/simple/ gatewatch` after a trial upload to test.pypi.org
(separate account and token) shows what users will get without spending the version number on pypi.org.

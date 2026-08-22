# Releasing Hirara to PyPI

Hirara publishes its pip-installable packages with **PyPI Trusted Publishing**
(OIDC). GitHub Actions proves the release came from this repository, and PyPI
mints a short-lived, project-scoped token for that one upload. **There is no API
token to create, store, or rotate**, and the workflow
([`.github/workflows/pypi-publish.yml`](.github/workflows/pypi-publish.yml))
never sees a long-lived secret.

## Packages published

| PyPI project   | Source path     | Import        | Version source              |
| -------------- | --------------- | ------------- | --------------------------- |
| `hirara-core`  | `hirara-core/`  | `hirara_core` | `hirara-core/pyproject.toml`|
| `hirara-web`   | `.` (repo root) | `hiraraweb`   | `pyproject.toml`            |
| `hirarapdf`    | `hirarapdf/`    | `hirarapdf`   | `hirarapdf/pyproject.toml`  |
| `hirarareader` | `hirarareader/` | `hirarareader`| `hirarareader/pyproject.toml`|
| `hiraranet`    | `hiraranet/`    | `hiraranet`   | `hiraranet/pyproject.toml`  |
| `hirarabrowser`| `hirarabrowser/`| `hirarabrowser`| `hirarabrowser/pyproject.toml`|
| `hirara` (SDK) | `hirara/`       | `hirara`      | `hirara/pyproject.toml`     |

Each package is versioned **independently**. A git tag only *triggers* a
release; the version that lands on PyPI is whatever each `pyproject.toml` says.
PyPI versions are **immutable** — you cannot overwrite one — so the workflow uses
`skip-existing: true`: already-published versions are skipped, and only packages
whose version changed are actually uploaded.

## One-time setup: configure the publishers

Do this once per package. It reserves the four unclaimed names at the same time
(a "pending publisher" both authorizes the upload *and* claims the name on first
publish, so no one can squat it in the meantime).

Every publisher uses the same Owner `lucasdmarshall`, Repository `Hirara`, and
Workflow `pypi-publish.yml` — but a **different Environment name per package**.
That is required: PyPI refuses two *pending* publishers that share an identical
owner/repo/workflow/environment tuple ("a pending trusted publisher matching
this configuration has already been registered for a different project name"),
so a blank environment can only ever cover one package. The environment names
below match the ones the workflow sends.

| PyPI project   | Environment name |
| -------------- | ---------------- |
| `hirara-core`  | `pypi-core`      |
| `hirara-web`   | `pypi-web`       |
| `hirarapdf`    | `pypi-pdf`       |
| `hirarareader` | `pypi-reader`    |
| `hiraranet`    | `pypi-net`       |
| `hirarabrowser`| `pypi-browser`   |
| `hirara`       | `pypi-sdk`       |

### On PyPI (https://pypi.org)

- **`hirara`** already exists (you own it). Open it → **Manage → Publishing →
  Add a new publisher**: Owner `lucasdmarshall`, Repository `Hirara`, Workflow
  `pypi-publish.yml`, Environment `pypi-sdk`.
- **`hirara-core`, `hirara-web`, `hirarapdf`, `hirarareader`, `hiraranet`, `hirarabrowser`** do not exist yet.
  Go to **Your account → Publishing** (https://pypi.org/manage/account/publishing/)
  — that page has the extra **PyPI Project Name** field, which is what makes it a
  *pending* publisher. Add one per name with its Environment from the table.

> GitHub creates the five environments (`pypi-core`, … `pypi-sdk`) automatically
> the first time the workflow runs. No manual GitHub setup is needed; if a run
> ever reports a missing environment, add it under **Settings → Environments**.

### On TestPyPI (https://test.pypi.org) — for dry runs

Repeat the **pending publisher** step for all five names on TestPyPI, using the
same Environment names. This lets you rehearse a release without touching PyPI.

## Dry run (TestPyPI)

1. GitHub → **Actions → Publish to PyPI → Run workflow**.
2. Set **target = `testpypi`** and run.
3. Confirm all five jobs are green and the versions appear on
   https://test.pypi.org/project/hirara/ etc.

> TestPyPI cannot resolve third-party deps (httpx, pypdf, …), so
> `pip install` *from* TestPyPI may fail — that is expected. The dry run
> validates the **build and upload**, not a full install.

## Real release

1. Bump the `version` in the `pyproject.toml` of every package you are releasing
   (and `__version__` where the package tracks it). Leave unchanged packages
   alone — their upload will simply be skipped.
2. Commit the bumps.
3. Publish. Either push a tag, or run the workflow manually:
   ```bash
   git tag -a v0.2.0 -m "…" && git push origin v0.2.0     # tag trigger
   # or, more reliably (see gotchas): Actions → Publish to PyPI → Run workflow
   # → target = pypi, or:  gh workflow run pypi-publish.yml --ref main -f target=pypi
   ```
4. The workflow builds and publishes to **real PyPI**. Watch the Actions run;
   each package job reports published-or-skipped (`skip-existing` keeps re-runs
   safe — only new versions upload).

## Verify

```bash
pip install "hirara[local]"
python -c "import hirara; hirara.configure(local=True); print([t['name'] for t in hirara.tools()])"
```

You should see the in-process tools (`pdf_read`, `web_fetch`, `office_read`, …)
with no hub running.

## Gotchas (learned in the first release, 2026-08-07)

- **PyPI limits you to 3 *pending* trusted publishers at once.** A pending
  publisher stops counting the moment its project is first published. With five
  new names, register ≤3, run the workflow (those become real projects), then
  register the rest and run again. `skip-existing` means the already-published
  ones are skipped on the second run.
- **Each publisher needs a distinct environment.** PyPI rejects two pending
  publishers that share the same owner/repo/workflow/environment; that is why
  every package has its own env name (see the table above).
- **`max-parallel: 1` is deliberate.** Fanning out all jobs at once starved the
  runner queue on this account (jobs waited ~15 min, then were auto-cancelled).
  Serial publishing is slower but reliable.
- **Prefer `workflow_dispatch` over the tag trigger if a run doesn't appear.**
  During a GitHub Actions incident the `v*` tag push spawned no run at all;
  a manual dispatch worked once Actions recovered. Check
  https://www.githubstatus.com/ if nothing starts.

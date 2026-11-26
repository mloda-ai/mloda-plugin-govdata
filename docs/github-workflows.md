# GitHub Workflows

This project uses GitHub Actions workflows to automate testing, security scanning, template synchronization, live tutorial runs with the tutorial web pages, releases, and publishing to PyPI.

## Test Workflow

**File:** `.github/workflows/test.yml`

**Triggers:**
- Push to any branch
- Pull request to `main`

**Purpose:** Runs the full test suite using tox across multiple Python versions (3.11, 3.12, 3.13, 3.14). This includes pytest, ruff linting, mypy type checking, and bandit security analysis.

**Requirements:** None. This workflow uses only public GitHub Actions and requires no secrets.

## Security Scan Workflow

**File:** `.github/workflows/security-scan.yaml`

**Triggers:**
- Scheduled: Every Monday at 9:00 AM UTC
- Manual dispatch (can be triggered from any branch)

**Purpose:** Performs CVE vulnerability scanning on the local package using pip-audit via tox. The workflow builds the package and scans its dependencies for known vulnerabilities.

**Requirements:** None. Uses only the default `GITHUB_TOKEN` with read permissions.

## Template Sync Workflow

**File:** `.github/workflows/template-sync.yaml`

**Triggers:**
- Scheduled: Every Thursday at 9:00 AM UTC
- Manual dispatch (can be triggered from any branch)

**Purpose:** Keeps this repository in sync with the upstream template repository ([mloda-plugin-template](https://github.com/mloda-ai/mloda-plugin-template)). The workflow:
1. Checks if there are new commits in the template repository
2. If new commits exist, creates a branch `chore/template-sync-YYYY-MM-DD`
3. Merges template changes into the branch
4. Opens a pull request for review

**Requirements:** None. Uses only the default `GITHUB_TOKEN` with write permissions for contents and pull-requests.

**Note:** If merge conflicts occur, the workflow will fail and manual resolution is required. Run locally:
```bash
git remote add template https://github.com/mloda-ai/mloda-plugin-template.git
git fetch template
git merge template/main
```

## Tutorials (live) Workflow

**File:** `.github/workflows/tutorials-live.yml`

**Triggers:**
- Manual dispatch only, with an optional `publish` tick box and a `runner` choice

**Purpose:** Runs every tutorial against the live sources. With `publish`, it then builds one web page per tutorial plus an index (`scripts/build_site.py`) and deploys them to GitHub Pages. The pages load marimo's viewer from a copy in the site, with marimo's license and third-party notices, not from a CDN. A cell that fails or stops, a page still linking the viewer on the CDN, missing viewer files, or a credential in a page, fails the run and publishes nothing.

**To publish:** **Actions** > **Tutorials (live)** > **Run workflow**, on the default branch, with `publish` ticked. The pages appear at `https://<owner>.github.io/mloda-plugin-govdata/`. From another branch the pages are not deployed: they stay an artifact of the run for one day, to look at first.

**Requirements:**
- `GENESIS_TOKEN` - a GENESIS-Online token, as a repository secret (on a fork: the fork's own secret)
- For `publish`: **Settings** > **Pages** > **Source** set to **GitHub Actions**; this creates the `github-pages` environment the deploy uses

**Self-hosted:** if a source refuses GitHub's runners, pick `runner: self-hosted`. The `tutorials` job then runs on a runner labelled `govdata-tutorials` and waits in the `self-hosted-runner` environment until a reviewer approves; the deploy stays on GitHub. Keep fork pull request workflows on "Require approval for all external contributors", give the environment a required reviewer and the `main` branch only, and register the runner with `--ephemeral` just before the run, so it takes this one job and leaves.

## Release Workflow

**File:** `.github/workflows/release.yaml`

**Triggers:**
- Manual dispatch only

**Purpose:** Automates semantic versioning and publishing to TestPyPI. The workflow:
1. Analyzes commits using [semantic-release](https://semantic-release.gitbook.io/) to determine the next version
2. Creates a GitHub release with changelog
3. Updates version in `pyproject.toml`
4. Builds the wheel once from the released commit
5. Publishes that wheel to [TestPyPI](https://test.pypi.org/project/mloda-plugin-govdata/) (job `publish_testpypi`, environment `testpypi`)
6. Attaches the same wheel to the GitHub release

**Requirements:**
- `SEMANTIC_RELEASE_TOKEN` - GitHub Personal Access Token with `repo` write permissions
- A TestPyPI Trusted Publisher (see [Trusted Publishing](#trusted-publishing)); no PyPI token is stored

## Publish to PyPI Workflow

**File:** `.github/workflows/publish-pypi.yaml`

**Triggers:**
- Manual dispatch only, with the released `version` (for example `0.5.1`) as input

**Purpose:** Downloads the wheel the Release workflow attached to the GitHub release and publishes it to [PyPI](https://pypi.org/project/mloda-plugin-govdata/) (job `publish_pypi`, environment `pypi`). PyPI gets byte for byte the file TestPyPI got, so check the TestPyPI release first.

**Requirements:** A PyPI Trusted Publisher (see [Trusted Publishing](#trusted-publishing)).

**Prerequisites:** Commits must follow the [Conventional Commits](https://www.conventionalcommits.org/) format for semantic-release to determine version bumps:
- `fix:` - Patch release (0.0.x)
- `feat:` - Minor release (0.x.0)
- `feat!:` or `BREAKING CHANGE:` - Major release (x.0.0)

## Setting Up Secrets

To configure the required secrets for the release workflow:

### SEMANTIC_RELEASE_TOKEN

1. Go to GitHub **Settings** > **Developer settings** > **Personal access tokens** > **Tokens (classic)**
2. Click **Generate new token (classic)**
3. Give it a descriptive name (e.g., "semantic-release")
4. Select the `repo` scope (full control of private repositories)
5. Click **Generate token** and copy the token
6. In your repository, go to **Settings** > **Secrets and variables** > **Actions**
7. Click **New repository secret**
8. Name: `SEMANTIC_RELEASE_TOKEN`
9. Value: Paste the token
10. Click **Add secret**

## Trusted Publishing

Uploads use [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/): the job's OIDC token is traded for a short-lived upload token, so no PyPI secret is stored. Set it up once per index:

| Index | Workflow | Environment |
|-------|----------|-------------|
| [test.pypi.org](https://test.pypi.org/manage/project/mloda-plugin-govdata/settings/publishing/) | `release.yaml` | `testpypi` |
| [pypi.org](https://pypi.org/manage/project/mloda-plugin-govdata/settings/publishing/) | `publish-pypi.yaml` | `pypi` |

1. On each index, open the project's **Publishing** settings and add a GitHub publisher with owner `mloda-ai`, repository `mloda-plugin-govdata`, and the workflow and environment from the table. A project that does not exist on the index yet takes a pending publisher from the account's **Publishing** page.
2. In the repository, go to **Settings** > **Environments** and create `testpypi` and `pypi`. Restricting `pypi` to the `main` branch or adding required reviewers is optional.

# Contributing to mloda-plugin-template

Thanks for considering a contribution to the **template** repo itself. This document is for people who want to improve the scaffold (CI workflows, examples, dev tooling, docs) that downstream plugin authors will inherit.

> **If you arrived here after clicking "Use this template" on GitHub:** this file does not apply to your new plugin repo. Follow the README's [Use this template](README.md#use-this-template) section, which includes a step that removes this file along with the other template-only community files.

By participating in this project, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) for dependency management
- `tox` for running checks (installed via the dev extras)

### Local Development Setup

1. Fork the repository and clone your fork:

```bash
git clone https://github.com/<your-username>/mloda-plugin-template.git
cd mloda-plugin-template
```

2. Create the virtualenv and install dependencies:

```bash
uv venv
source .venv/bin/activate
uv sync --all-extras
```

3. Verify your setup by running the full check suite:

```bash
tox
```

## Code Style

`tox` is the gate. It runs:

- `pytest` for tests
- `ruff format --check --line-length 120` for formatting
- `ruff check` for linting
- `mypy --strict --ignore-missing-imports` for type checking
- `bandit -c pyproject.toml -r -q` for security

All of these must pass before a PR is mergeable. A separate `tox -e security` environment runs `pip-audit` for CVE scanning of installed dependencies.

### Conventions

- **Type hints**: use modern forms (`list[str]`, `dict[str, int]`, `X | None`).
- **Line length**: 120.
- **Tests**: every new feature or bug fix must come with tests; follow the patterns in `tests/` and `placeholder/.../tests/`.
- **Commits**: use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `style:`, `ci:`, `build:`, `perf:`). semantic-release uses standard rules: `feat:` triggers a minor bump, all others trigger a patch (see `.releaserc.yaml`).
- **No `Co-Authored-By` lines or other AI agent mentions** in commit messages or PR descriptions.

## Pull Request Workflow

1. Create a feature branch from `main`:

```bash
git checkout -b fix/short-description
```

2. Make your changes; run `tox` locally and confirm it passes.
3. Commit using Conventional Commits format.
4. Push to your fork and open a pull request targeting `main`.
5. CI runs the full tox suite. All checks must pass before merge.

## Reporting Issues

Use the issue form at [.github/ISSUE_TEMPLATE/issue.yml](.github/ISSUE_TEMPLATE/issue.yml). It asks for a one-sentence summary, reproduction or motivation, optional code pointers, and an optional definition of done. See the **Issue Creation** section in [AGENTS.md](AGENTS.md) for more guidance.

## Plugin Development vs. Template Contribution

This repo is the **scaffold** for new mloda plugins, not a plugin itself. If you want to:

- **Build a new plugin**: click "Use this template" on GitHub, then follow [docs/getting-started.md](docs/getting-started.md) and the README's [Use this template](README.md#use-this-template) section. The full plugin development walkthrough lives in [mloda-registry/docs/guides/](https://github.com/mloda-ai/mloda-registry/tree/main/docs/guides/).
- **Contribute to the core framework**: see [mloda](https://github.com/mloda-ai/mloda).
- **Contribute to community plugins**: see [mloda-registry](https://github.com/mloda-ai/mloda-registry).

## License

By contributing, you agree that your contributions will be licensed under the [Apache License, Version 2.0](LICENSE).

# sentry-report-kit

A small, installable Python CLI project for Sentry report tooling.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Install (from GitHub)

Replace `<your-org>` once the repo is pushed.

```bash
uv tool install git+https://github.com/<your-org>/sentry-report-kit.git
```

Or with pip:

```bash
pip install git+https://github.com/<your-org>/sentry-report-kit.git
```

## Usage

```bash
sentry-report-kit --help
sentry-report-kit --version
sentry-report-kit --healthcheck
```

## Local development

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## Project layout

```text
src/sentry_report_kit/   # package code
tests/                   # test suite
pyproject.toml           # packaging + tooling config
```

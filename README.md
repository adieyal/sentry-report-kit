# sentry-report-kit

A standalone, installable CLI for generating Sentry issue reports without Django.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- `SENTRY_TOKEN` with access to your org/project

## Install (from GitHub)

```bash
uv tool install git+https://github.com/adieyal/sentry-report-kit.git
```

Or with pip:

```bash
pip install git+https://github.com/adieyal/sentry-report-kit.git
```

## Usage

```bash
sentry-report-kit --help
sentry-report-kit --version
sentry-report-kit --healthcheck
```

Generate a report directly from Sentry API (no Django):

```bash
export SENTRY_TOKEN=...your-token...
sentry-report-kit report --org restoke --project restoke --days 30 --format html --output /tmp/sentry_report.html
```

JSON output:

```bash
sentry-report-kit report --org restoke --project restoke --days 30 --format json --output /tmp/sentry_report.json
```

Print report output to stdout:

```bash
sentry-report-kit report --org restoke --project restoke --format json
```

### `report` command options

```bash
sentry-report-kit report \
  [--org <slug>] \
  [--project <slug>] \
  [--query <sentry-query>] \
  [--days <int>] \
  [--top <int>] \
  [--limit <int>] \
  [--format html|json] \
  [--output <path>] \
  [--token <token>]
```

- `--org`: Sentry org slug (default: `restoke`)
- `--project`: Sentry project slug (default: `restoke`)
- `--query`: Sentry search query (default: `is:unresolved`)
- `--days`: lookback window in days (default: `30`)
- `--top`: number of top issues included in report (default: `10`)
- `--limit`: max issues fetched from Sentry API (default: `200`)
- `--format`: output format (`html` or `json`, default: `html`)
- `--output`: output file path; when omitted, content is printed to stdout
- `--token`: Sentry token; if omitted, `SENTRY_TOKEN` is used

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

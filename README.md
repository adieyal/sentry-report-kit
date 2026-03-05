# sentry-report-kit

A standalone, installable CLI for generating Sentry issue reports without Django.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- `SENTRY_TOKEN` with access to your org/project
- `OPENAI_API_KEY` only if using `--report-llm-analysis`

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

## Generate report (same HTML report format)

Automated analysis:

```bash
export SENTRY_TOKEN=...your-token...
sentry-report-kit report --org restoke --project restoke --days 30 --format html --output /tmp/sentry_report.html
```

LLM-assisted analysis (same report format/template, richer narrative copy):

```bash
export SENTRY_TOKEN=...your-token...
export OPENAI_API_KEY=...your-openai-key...
sentry-report-kit report --org restoke --project restoke --days 30 --format html --report-llm-analysis --llm-model gpt-4.1-mini --output /tmp/sentry_report_llm.html
```

JSON output:

```bash
sentry-report-kit report --org restoke --project restoke --days 30 --format json --output /tmp/sentry_report.json
```

## Local development

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

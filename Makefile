PYTHON ?= python3

.PHONY: help sync lint format format-check typecheck test check

help:
	@echo "Available targets:"
	@echo "  make sync         - Install/update dependencies with uv"
	@echo "  make lint         - Run ruff lint checks"
	@echo "  make format       - Format code with ruff"
	@echo "  make format-check - Check formatting with ruff"
	@echo "  make typecheck    - Run mypy"
	@echo "  make test         - Run pytest"
	@echo "  make check        - Run lint, format-check, typecheck, test"

sync:
	uv sync --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src

test:
	uv run pytest

check: lint format-check typecheck test

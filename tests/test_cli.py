from __future__ import annotations

import pytest

from sentry_report_kit.cli import build_parser


def test_parser_accepts_version_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["--version"])

    assert args.version is True
    assert args.healthcheck is False


def test_parser_without_args_defaults_to_help_flow() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert args.version is False
    assert args.healthcheck is False


def test_parser_accepts_healthcheck_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["--healthcheck"])

    assert args.healthcheck is True
    assert args.version is False


@pytest.mark.parametrize("flag", ["--version", "--healthcheck"])
def test_parser_allows_known_flags(flag: str) -> None:
    parser = build_parser()

    args = parser.parse_args([flag])

    assert getattr(args, flag.lstrip("-").replace("-", "_")) is True


def test_report_parser_accepts_llm_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "report",
            "--report-llm-analysis",
            "--llm-model",
            "gpt-4.1-mini",
            "--llm-max-tokens",
            "900",
            "--openai-api-key",
            "x",
        ]
    )

    assert args.command == "report"
    assert args.report_llm_analysis is True
    assert args.llm_model == "gpt-4.1-mini"
    assert args.llm_max_tokens == 900


def test_report_parser_accepts_window_and_mode_alias_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "report",
            "--start",
            "2026-02-01",
            "--end",
            "2026-03-01",
            "--report-json",
        ]
    )

    assert args.start == "2026-02-01"
    assert args.end == "2026-03-01"
    assert args.report_json is True
    assert args.report_html is False


def test_help_shows_defaults_and_examples(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["report", "--help"])
    captured = capsys.readouterr()
    report_help = captured.out

    assert "default: 30" in report_help
    assert "default: restoke" in report_help
    assert "Examples:" in report_help


def test_report_mode_flags_are_mutually_exclusive() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["report", "--format", "json", "--report-html"])

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

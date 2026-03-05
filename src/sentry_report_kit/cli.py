from __future__ import annotations

import argparse
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentry-report-kit",
        description="Utilities for Sentry issue report payloads.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print package version and exit.",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Run a lightweight healthcheck and exit.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(version("sentry-report-kit"))
        return

    if args.healthcheck:
        print("ok")
        return

    parser.print_help()

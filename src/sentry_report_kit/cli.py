from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import version

from sentry_report_kit.reporting import (
    ReportError,
    generate_report_payload,
    payload_to_json,
    render_html,
)


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

    subparsers = parser.add_subparsers(dest="command")
    report_parser = subparsers.add_parser(
        "report", help="Generate report from Sentry API."
    )
    report_parser.add_argument("--org", default="restoke", help="Sentry org slug.")
    report_parser.add_argument(
        "--project", default="restoke", help="Sentry project slug."
    )
    report_parser.add_argument(
        "--query", default="is:unresolved", help="Sentry search query."
    )
    report_parser.add_argument(
        "--days", type=int, default=30, help="Lookback window in days."
    )
    report_parser.add_argument(
        "--top", type=int, default=10, help="Top issues to include."
    )
    report_parser.add_argument(
        "--limit", type=int, default=200, help="Sentry issue fetch limit."
    )
    report_parser.add_argument(
        "--format",
        choices=("json", "html"),
        default="html",
        help="Output format.",
    )
    report_parser.add_argument(
        "--output", default=None, help="Output file path. Defaults to stdout."
    )
    report_parser.add_argument(
        "--token",
        default=None,
        help="Sentry auth token. Defaults to SENTRY_TOKEN env var.",
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

    if args.command == "report":
        _run_report(args)
        return

    parser.print_help()


def _run_report(args: argparse.Namespace) -> None:
    token = args.token or os.getenv("SENTRY_TOKEN")
    if not token:
        raise SystemExit("Missing Sentry token. Provide --token or set SENTRY_TOKEN.")

    print("[sentry-report-kit] Fetching issues from Sentry...", file=sys.stderr)
    try:
        payload = generate_report_payload(
            org=args.org,
            project=args.project,
            query=args.query,
            days=args.days,
            top=args.top,
            limit=args.limit,
            token=token,
        )
    except ReportError as exc:
        raise SystemExit(f"Report generation failed: {exc}") from exc

    print("[sentry-report-kit] Building output...", file=sys.stderr)
    content = (
        payload_to_json(payload) if args.format == "json" else render_html(payload)
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(
            f"[sentry-report-kit] Wrote {args.format} report to {args.output}",
            file=sys.stderr,
        )
        return

    print(content)

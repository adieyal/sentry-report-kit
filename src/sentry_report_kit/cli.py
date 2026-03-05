from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version

from sentry_report_kit.reporting import (
    ReportError,
    ReportRequest,
    generate_report_payload,
    payload_to_json,
    render_html,
)


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentry-report-kit",
        description="Utilities for Sentry issue report payloads.",
        formatter_class=HelpFormatter,
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
        "report",
        help="Generate report from Sentry API.",
        description="Generate report from Sentry API.",
        formatter_class=HelpFormatter,
        epilog=(
            "Examples:\n"
            "  sentry-report-kit report --report-html --days 30 --output /tmp/sentry_report.html\n"
            "  sentry-report-kit report --report-json --days 30 --output /tmp/sentry_report.json\n"
            "  sentry-report-kit report --report-html --start 2026-02-01 --end 2026-03-01 "
            "--report-llm-analysis --llm-model gpt-4.1-mini --output /tmp/sentry_report_llm.html"
        ),
    )
    report_parser.add_argument("--org", default="restoke", help="Sentry org slug.")
    report_parser.add_argument(
        "--project",
        default="restoke",
        help="Sentry project slug.",
    )
    report_parser.add_argument(
        "--query",
        default="is:unresolved",
        help="Sentry search query.",
    )
    report_parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback window in days.",
    )
    report_parser.add_argument(
        "--start",
        default=None,
        help="Report window start date (YYYY-MM-DD, UTC).",
    )
    report_parser.add_argument(
        "--end",
        default=None,
        help="Report window end date (YYYY-MM-DD, UTC).",
    )
    report_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Top issues to include.",
    )
    report_parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Sentry issue fetch limit.",
    )
    mode_group = report_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--format",
        choices=("json", "html"),
        default="html",
        help="Output format.",
    )
    mode_group.add_argument(
        "--report-json",
        action="store_true",
        dest="report_json",
        help="Alias for --format json.",
    )
    mode_group.add_argument(
        "--report-html",
        action="store_true",
        dest="report_html",
        help="Alias for --format html.",
    )
    report_parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Defaults to stdout.",
    )
    report_parser.add_argument(
        "--token",
        default=None,
        help="Sentry auth token. Defaults to SENTRY_TOKEN env var.",
    )
    report_parser.add_argument(
        "--report-llm-analysis",
        action="store_true",
        dest="report_llm_analysis",
        help="Generate report narrative text with OpenAI.",
    )
    report_parser.add_argument(
        "--llm-model",
        default="gpt-4.1-mini",
        help="Model used for --report-llm-analysis.",
    )
    report_parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=1200,
        help="Max output tokens for LLM analysis.",
    )
    report_parser.add_argument(
        "--openai-api-key",
        default=None,
        help="OpenAI API key. Defaults to OPENAI_API_KEY env var.",
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

    openai_api_key = args.openai_api_key or os.getenv("OPENAI_API_KEY")

    output_format = args.format
    if args.report_json:
        output_format = "json"
    elif args.report_html:
        output_format = "html"

    print("[sentry-report-kit] Resolving report window...", file=sys.stderr)
    start, end = _resolve_report_window(start=args.start, end=args.end)

    print("[sentry-report-kit] Fetching issues from Sentry...", file=sys.stderr)
    try:
        request = ReportRequest(
            org=args.org,
            project=args.project,
            query=args.query,
            days=args.days if start is None else None,
            start=start,
            end=end,
            top=args.top,
            limit=args.limit,
            use_llm_analysis=args.report_llm_analysis,
            llm_model=args.llm_model,
            llm_max_tokens=args.llm_max_tokens,
        )
        payload = generate_report_payload(
            request=request,
            sentry_token=token,
            openai_api_key=openai_api_key,
        )
    except ReportError as exc:
        raise SystemExit(f"Report generation failed: {exc}") from exc

    print("[sentry-report-kit] Building output...", file=sys.stderr)
    content = payload_to_json(payload) if output_format == "json" else render_html(payload)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(
            f"[sentry-report-kit] Wrote {output_format} report to {args.output}",
            file=sys.stderr,
        )
        return

    print(content)


def _resolve_report_window(*, start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    if start is None and end is None:
        return None, None
    if start is None or end is None:
        raise SystemExit("Report generation failed: Provide both --start and --end.")

    start_dt = _parse_date(start)
    end_dt = _parse_date(end)
    if start_dt >= end_dt:
        raise SystemExit("Report generation failed: --start must be earlier than --end.")
    return start_dt, end_dt


def _parse_date(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"Report generation failed: Invalid date '{value}'. Expected YYYY-MM-DD.") from exc
    return parsed.replace(tzinfo=UTC)

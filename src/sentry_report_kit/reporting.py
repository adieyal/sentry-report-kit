from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any

import requests

SENTRY_API_BASE = "https://sentry.io/api/0"


class ReportError(Exception):
    """Raised when report generation fails."""


@dataclass(frozen=True)
class IssueItem:
    issue_id: str
    short_id: str
    title: str
    permalink: str
    status: str
    level: str
    total_events: int
    affected_users: int
    events_24h: int
    events_per_hour_24h: float
    first_seen: str | None
    last_seen: str | None
    age_days: int
    platform: str
    issue_type: str
    culprit: str
    file: str
    function: str
    category: str
    priority_hint: str


@dataclass(frozen=True)
class CategorySummary:
    category: str
    issues: int
    total_events: int
    total_users: int


@dataclass(frozen=True)
class CategoryTopIssues:
    category: str
    issues: list[IssueItem]


@dataclass(frozen=True)
class ReportTotals:
    total_events: int
    total_issues: int
    unresolved_issues: int
    top_events_total: int


@dataclass(frozen=True)
class ReportPayload:
    schema_version: str
    generated_at: str
    org: str
    project: str
    query: str
    window_start: str
    window_end: str
    totals: ReportTotals
    categories: list[CategorySummary]
    top_issues: list[IssueItem]
    category_top_issues: list[CategoryTopIssues]
    analysis: dict[str, Any]


def generate_report_payload(
    *,
    org: str,
    project: str,
    query: str,
    days: int,
    top: int,
    limit: int,
    token: str,
    timeout_seconds: float = 20.0,
) -> ReportPayload:
    if days <= 0:
        raise ReportError("--days must be a positive integer.")
    if top <= 0:
        raise ReportError("--top must be a positive integer.")
    if limit <= 0:
        raise ReportError("--limit must be a positive integer.")

    window_end = datetime.now(UTC)
    window_start = window_end - timedelta(days=days)

    issues_raw = _fetch_report_issues(
        org=org,
        project=project,
        query=query,
        token=token,
        start=window_start,
        end=window_end,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )

    enriched: list[IssueItem] = []
    for index, issue in enumerate(issues_raw):
        issue_id = str(issue.get("id", ""))
        events_24h = 0
        if issue_id and index < top:
            events_24h = _fetch_events_24h(
                org=org,
                issue_id=issue_id,
                token=token,
                end=window_end,
                timeout_seconds=timeout_seconds,
            )
        enriched.append(
            _to_issue_item(issue=issue, events_24h=events_24h, window_end=window_end)
        )

    sorted_issues = sorted(enriched, key=lambda item: item.total_events, reverse=True)
    top_issues = sorted_issues[:top]
    categories = _build_category_summaries(sorted_issues)
    category_top = _build_category_top_issues(sorted_issues, per_category=3)
    totals = ReportTotals(
        total_events=sum(item.total_events for item in sorted_issues),
        total_issues=len(sorted_issues),
        unresolved_issues=sum(
            1 for item in sorted_issues if item.status.lower() == "unresolved"
        ),
        top_events_total=sum(item.total_events for item in top_issues),
    )

    payload = ReportPayload(
        schema_version="1",
        generated_at=_iso(datetime.now(UTC)),
        org=org,
        project=project,
        query=query,
        window_start=_iso(window_start),
        window_end=_iso(window_end),
        totals=totals,
        categories=categories,
        top_issues=top_issues,
        category_top_issues=category_top,
        analysis=_build_automated_analysis(
            totals=totals,
            categories=categories,
            top_issues=top_issues,
        ),
    )
    return payload


def payload_to_json(payload: ReportPayload) -> str:
    return json.dumps(asdict(payload), indent=2)


def render_html(payload: ReportPayload) -> str:
    template = (
        resources.files("sentry_report_kit.templates")
        .joinpath("report.html")
        .read_text(encoding="utf-8")
    )
    report_json = payload_to_json(payload)
    return template.replace("__REPORT_JSON__", report_json)


def _fetch_report_issues(
    *,
    org: str,
    project: str,
    query: str,
    token: str,
    start: datetime,
    end: datetime,
    limit: int,
    timeout_seconds: float,
) -> list[dict[str, object]]:
    url = f"{SENTRY_API_BASE}/projects/{org}/{project}/issues/"
    params: dict[str, str | int] = {
        "query": query,
        "sort": "freq",
        "limit": limit,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "statsPeriod": "",
    }
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        url, params=params, headers=headers, timeout=timeout_seconds
    )
    _raise_for_status(response)
    payload = response.json()
    if not isinstance(payload, list):
        raise ReportError("Sentry response payload is not a list of issues.")
    issues = [item for item in payload if isinstance(item, dict)]
    return issues


def _fetch_events_24h(
    *,
    org: str,
    issue_id: str,
    token: str,
    end: datetime,
    timeout_seconds: float,
) -> int:
    url = f"{SENTRY_API_BASE}/organizations/{org}/issues/{issue_id}/stats/"
    params = {
        "start": (end - timedelta(hours=24)).isoformat(),
        "end": end.isoformat(),
        "interval": "1h",
    }
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        url, params=params, headers=headers, timeout=timeout_seconds
    )
    if response.status_code == 404:
        return 0
    _raise_for_status(response)
    payload = response.json()
    if not isinstance(payload, list):
        return 0
    total = 0
    for point in payload:
        if isinstance(point, list) and len(point) >= 2:
            total += _parse_int(point[1])
    return total


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ReportError(
            f"Sentry API error ({response.status_code}): {response.text}"
        ) from exc


def _to_issue_item(
    *, issue: dict[str, object], events_24h: int, window_end: datetime
) -> IssueItem:
    metadata = issue.get("metadata") if isinstance(issue.get("metadata"), dict) else {}
    metadata_dict = metadata if isinstance(metadata, dict) else {}

    first_seen = _parse_timestamp(issue.get("firstSeen"))
    last_seen = _parse_timestamp(issue.get("lastSeen"))
    category = _categorize_issue(
        title=str(issue.get("title", "")),
        issue_type=str(metadata_dict.get("type", issue.get("type", "-"))),
        culprit=str(issue.get("culprit", "-")),
        file=str(metadata_dict.get("filename", "-")),
        function=str(metadata_dict.get("function", "-")),
        platform=str(issue.get("platform", "-")),
    )

    return IssueItem(
        issue_id=str(issue.get("id", "")),
        short_id=str(issue.get("shortId", issue.get("id", "?"))),
        title=str(issue.get("title", "No title")),
        permalink=str(issue.get("permalink", "")),
        status=str(issue.get("status", "")),
        level=str(issue.get("level", "error")),
        total_events=_parse_int(issue.get("count", 0)),
        affected_users=_parse_int(issue.get("userCount", 0)),
        events_24h=events_24h,
        events_per_hour_24h=round(events_24h / 24, 3),
        first_seen=_iso(first_seen) if first_seen else None,
        last_seen=_iso(last_seen) if last_seen else None,
        age_days=_age_days(first_seen, window_end),
        platform=str(issue.get("platform", "-")),
        issue_type=str(metadata_dict.get("type", issue.get("type", "-"))),
        culprit=str(issue.get("culprit", "-")),
        file=str(metadata_dict.get("filename", "-")),
        function=str(metadata_dict.get("function", "-")),
        category=category,
        priority_hint=_priority_hint(
            total_events=_parse_int(issue.get("count", 0)),
            events_24h=events_24h,
            affected_users=_parse_int(issue.get("userCount", 0)),
        ),
    )


def _build_category_summaries(issues: list[IssueItem]) -> list[CategorySummary]:
    category_map: dict[str, dict[str, int]] = {}
    for issue in issues:
        current = category_map.setdefault(
            issue.category,
            {"issues": 0, "total_events": 0, "total_users": 0},
        )
        current["issues"] += 1
        current["total_events"] += issue.total_events
        current["total_users"] += issue.affected_users

    summaries = [
        CategorySummary(
            category=name,
            issues=data["issues"],
            total_events=data["total_events"],
            total_users=data["total_users"],
        )
        for name, data in category_map.items()
    ]
    return sorted(summaries, key=lambda row: row.total_events, reverse=True)


def _build_category_top_issues(
    issues: list[IssueItem], per_category: int
) -> list[CategoryTopIssues]:
    by_category: dict[str, list[IssueItem]] = {}
    for issue in issues:
        by_category.setdefault(issue.category, []).append(issue)

    result = [
        CategoryTopIssues(
            category=category,
            issues=sorted(items, key=lambda item: item.total_events, reverse=True)[
                :per_category
            ],
        )
        for category, items in by_category.items()
    ]
    return sorted(
        result,
        key=lambda row: sum(issue.total_events for issue in row.issues),
        reverse=True,
    )


def _build_automated_analysis(
    *,
    totals: ReportTotals,
    categories: list[CategorySummary],
    top_issues: list[IssueItem],
) -> dict[str, Any]:
    total_events = totals.total_events
    concentration = (
        (totals.top_events_total / total_events * 100) if total_events > 0 else 0.0
    )

    lead = categories[0] if categories else None
    second = categories[1] if len(categories) > 1 else None
    top_issue = top_issues[0] if top_issues else None

    hero = f"Top issues drive {concentration:.1f}% of all events in this window."
    if lead and total_events > 0:
        lead_pct = lead.total_events / total_events * 100
        hero += (
            " Largest category: "
            f"{lead.category} ({lead.total_events} events, {lead_pct:.1f}%)."
        )
    if second and total_events > 0:
        second_pct = second.total_events / total_events * 100
        hero += (
            " Next: "
            f"{second.category} ({second.total_events} events, {second_pct:.1f}%)."
        )
    if top_issue:
        hero += (
            " Highest-volume issue: "
            f"{top_issue.short_id} ({top_issue.total_events} events)."
        )

    return {
        "mode": "automated",
        "hero_callout": hero,
        "category_summary": (
            f"{len(categories)} categories detected. "
            "Prioritize the top 2 to cut noise fastest."
        ),
    }


def _categorize_issue(
    *,
    title: str,
    issue_type: str,
    culprit: str,
    file: str,
    function: str,
    platform: str,
) -> str:
    text = " ".join(
        [
            title.lower(),
            issue_type.lower(),
            culprit.lower(),
            file.lower(),
            function.lower(),
        ]
    )

    if "lightspeed" in text:
        return "POS integration: Lightspeed"
    if "square" in text:
        return "POS integration: Square"
    if "toast" in text:
        return "POS integration: Toast"
    if "xero" in text or "invalid_grant" in text:
        return "Accounting integration: Xero"
    if "analysis" in text or "langchain" in text:
        return "AI/analysis pipeline"
    if "analytics" in text:
        return "Analytics pipeline"
    if "n+1" in text or "query" in text:
        return "Performance: database"
    if platform.lower() == "javascript":
        return "Frontend (web app)"
    return "Backend/runtime"


def _priority_hint(*, total_events: int, events_24h: int, affected_users: int) -> str:
    if total_events >= 100 or events_24h >= 20 or affected_users >= 10_000:
        return "P0"
    if total_events >= 20 or events_24h >= 5:
        return "P1"
    return "P2"


def _parse_int(value: object) -> int:
    if value is None:
        return 0
    return int(str(value))


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _age_days(first_seen: datetime | None, window_end: datetime) -> int:
    if first_seen is None:
        return 0
    return max(0, int((window_end - first_seen).total_seconds() // 86400))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

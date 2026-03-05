from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any

import requests
from openai import OpenAI

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
    type: str
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


@dataclass(frozen=True)
class ReportRequest:
    org: str
    project: str
    query: str
    days: int | None = 30
    start: datetime | None = None
    end: datetime | None = None
    top: int = 10
    limit: int = 200
    timeout_seconds: float = 20.0
    use_llm_analysis: bool = False
    llm_model: str = "gpt-4.1-mini"
    llm_max_tokens: int = 1200


def generate_report_payload(
    *, request: ReportRequest, sentry_token: str, openai_api_key: str | None = None
) -> ReportPayload:
    _validate_request(request)

    window_start, window_end = _resolve_window(request)

    issues_raw = _fetch_report_issues(
        org=request.org,
        project=request.project,
        query=request.query,
        token=sentry_token,
        start=window_start,
        end=window_end,
        limit=request.limit,
        timeout_seconds=request.timeout_seconds,
    )

    enriched: list[IssueItem] = []
    for index, issue in enumerate(issues_raw):
        issue_id = str(issue.get("id", ""))
        events_24h = 0
        if issue_id and index < request.top:
            events_24h = _fetch_events_24h(
                org=request.org,
                issue_id=issue_id,
                token=sentry_token,
                end=window_end,
                timeout_seconds=request.timeout_seconds,
            )
        enriched.append(_to_issue_item(issue=issue, events_24h=events_24h, window_end=window_end))

    sorted_issues = sorted(enriched, key=lambda item: item.total_events, reverse=True)
    top_issues = sorted_issues[: request.top]
    categories = _build_category_summaries(sorted_issues)
    category_top = _build_category_top_issues(sorted_issues, per_category=3)
    totals = ReportTotals(
        total_events=sum(item.total_events for item in sorted_issues),
        total_issues=len(sorted_issues),
        unresolved_issues=sum(1 for item in sorted_issues if item.status.lower() == "unresolved"),
        top_events_total=sum(item.total_events for item in top_issues),
    )

    automated_analysis = _build_automated_analysis(
        totals=totals,
        categories=categories,
        top_issues=top_issues,
    )
    analysis = automated_analysis
    if request.use_llm_analysis:
        llm_analysis = _generate_llm_analysis(
            model_name=request.llm_model,
            max_tokens=request.llm_max_tokens,
            payload={
                "org": request.org,
                "project": request.project,
                "query": request.query,
                "window_start": _iso(window_start),
                "window_end": _iso(window_end),
                "totals": asdict(totals),
                "categories": [asdict(item) for item in categories],
                "top_issues": [asdict(item) for item in top_issues],
            },
            openai_api_key=openai_api_key,
        )
        analysis = _merge_llm_analysis_with_automated(
            automated_analysis=automated_analysis,
            llm_analysis=llm_analysis,
        )
        analysis["model"] = request.llm_model

    return ReportPayload(
        schema_version="1",
        generated_at=_iso(datetime.now(UTC)),
        org=request.org,
        project=request.project,
        query=request.query,
        window_start=_iso(window_start),
        window_end=_iso(window_end),
        totals=totals,
        categories=categories,
        top_issues=top_issues,
        category_top_issues=category_top,
        analysis=analysis,
    )


def payload_to_json(payload: ReportPayload) -> str:
    return json.dumps(asdict(payload), indent=2)


def render_html(payload: ReportPayload) -> str:
    template_path = resources.files("sentry_report_kit.templates").joinpath("report.html")
    template = template_path.read_text(encoding="utf-8")
    # Prevent premature </script> termination when embedding JSON in HTML.
    safe_report_json = payload_to_json(payload).replace("</", "<\\/")
    return template.replace("__REPORT_JSON__", safe_report_json)


def _validate_request(request: ReportRequest) -> None:
    if request.days is not None and request.days <= 0:
        raise ReportError("--days must be a positive integer.")
    if request.top <= 0:
        raise ReportError("--top must be a positive integer.")
    if request.limit <= 0:
        raise ReportError("--limit must be a positive integer.")


def _resolve_window(request: ReportRequest) -> tuple[datetime, datetime]:
    if (request.start and not request.end) or (request.end and not request.start):
        raise ReportError("Provide both --start and --end.")
    if request.days is not None and (request.start or request.end):
        raise ReportError("--days cannot be combined with --start/--end.")
    if request.start and request.end:
        if request.start >= request.end:
            raise ReportError("--start must be earlier than --end.")
        return request.start, request.end

    days = 30 if request.days is None else request.days
    if days <= 0:
        raise ReportError("--days must be a positive integer.")
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    return start, end


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
    response = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
    _raise_for_status(response)
    payload = response.json()
    if not isinstance(payload, list):
        raise ReportError("Sentry response payload is not a list of issues.")
    return [item for item in payload if isinstance(item, dict)]


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
    response = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
    if response.status_code == 404:
        return 0
    _raise_for_status(response)
    payload = response.json()
    return _sum_events_from_stats_payload(payload)


def _sum_events_from_stats_payload(payload: object) -> int:
    if not isinstance(payload, list):
        raise ReportError("Sentry stats payload is not a list.")
    total = 0
    for point in payload:
        if isinstance(point, list) and len(point) >= 2:
            total += _parse_int(point[1])
    return total


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ReportError(f"Sentry API error ({response.status_code}): {response.text}") from exc


def _to_issue_item(*, issue: dict[str, object], events_24h: int, window_end: datetime) -> IssueItem:
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
        type=str(metadata_dict.get("type", issue.get("type", "-"))),
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


def _build_category_top_issues(issues: list[IssueItem], per_category: int) -> list[CategoryTopIssues]:
    by_category: dict[str, list[IssueItem]] = {}
    for issue in issues:
        by_category.setdefault(issue.category, []).append(issue)

    result = [
        CategoryTopIssues(
            category=category,
            issues=sorted(
                items,
                key=lambda item: item.total_events,
                reverse=True,
            )[:per_category],
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
    concentration = (totals.top_events_total / total_events * 100) if total_events > 0 else 0.0

    lead = categories[0] if categories else None
    second = categories[1] if len(categories) > 1 else None
    top_issue = top_issues[0] if top_issues else None

    hero = f"Top issues drive {concentration:.1f}% of all events in this window."
    if lead and total_events > 0:
        lead_pct = lead.total_events / total_events * 100
        hero += f" Largest category: {lead.category} ({lead.total_events} events, {lead_pct:.1f}%)."
    if second and total_events > 0:
        second_pct = second.total_events / total_events * 100
        hero += f" Next: {second.category} ({second.total_events} events, {second_pct:.1f}%)."
    if top_issue:
        hero += f" Highest-volume issue: {top_issue.short_id} ({top_issue.total_events} events)."

    action_plan = [
        {
            "title": category.category,
            "body": _next_step_for_category(category.category),
            "owner": _owner_for_category(category.category),
        }
        for category in categories[:4]
    ]
    if not action_plan:
        action_plan.append(
            {
                "title": "No category data",
                "body": "No issues returned for this window. Adjust filters or date range.",
                "owner": "Triage",
            }
        )

    important_issues: list[dict[str, Any]] = []
    for issue in top_issues[:5]:
        important_issues.append(
            {
                "short_id": issue.short_id,
                "title": issue.title,
                "why_important": (
                    f"{issue.total_events} events in window, "
                    f"{issue.events_24h}/24h recent burn, "
                    f"{issue.affected_users} affected users."
                ),
                "risk_level": "high" if issue.total_events >= 100 else "medium",
                "confidence": "medium",
                "next_checks": "Inspect recent events, stacktrace grouping, and retry loops.",
            }
        )

    return {
        "mode": "automated",
        "hero_callout": hero,
        "category_summary": (f"{len(categories)} categories detected. Prioritize the top 2 to cut noise fastest."),
        "section_copy": {
            "breakdown": "Volume by category and ownership. Prioritize top categories first.",
            "issues": "Issue list ranked by impact and burn to focus investigation effort.",
            "triage": "Age vs burn-rate map highlights long-running, high-noise items.",
            "details": "Selected issue context, impact, and recommended next investigative step.",
            "actions": "Concrete fixes grouped by highest leverage first.",
        },
        "important_issues": important_issues,
        "issue_insights": [],
        "action_plan": action_plan,
    }


def _owner_for_category(category: str) -> str:
    if category.startswith("POS integration"):
        return "Integrations"
    if category == "Frontend (web app)":
        return "Frontend"
    if category == "Analytics pipeline":
        return "Data / Analytics"
    if category == "Performance: database":
        return "Backend"
    if category == "Accounting integration: Xero":
        return "Integrations"
    if category == "AI/analysis pipeline":
        return "AI team"
    return "Backend"


def _next_step_for_category(category: str) -> str:
    if category.startswith("POS integration"):
        return (
            "Validate provider responses before parsing, classify auth/data errors, and add exponential retry backoff."
        )
    if category == "Frontend (web app)":
        return "Add route/action breadcrumbs and split generic frontend errors into actionable groups."
    if category == "Accounting integration: Xero":
        return "Detect invalid_grant states, mark accounts for reconnect, and suppress retries until re-auth."
    if category == "AI/analysis pipeline":
        return "Add request context and retry caps, then tune queue backpressure."
    if category == "Performance: database":
        return "Profile query fan-out and batch or prefetch hot paths."
    if category == "Analytics pipeline":
        return "Attach tenant/job context and make jobs idempotent to avoid duplicate failures."
    return "Assign ownership and add focused instrumentation to reduce repeat volume."


def _build_llm_analysis_prompt(*, payload: dict[str, Any]) -> str:
    compact_payload = _compact_payload_for_llm(payload)
    return (
        "You are generating concise Sentry triage report commentary.\n"
        "The response schema is enforced by the API.\n"
        "Constraints:\n"
        "- Be data-driven from provided payload only.\n"
        "- Do not claim unknown causes or certainty.\n"
        "- Prioritize interpretation: explain why issues matter and what to check next.\n"
        "- action_plan must contain 1-4 entries.\n"
        "- important_issues must contain 1-5 entries from provided top_issues.\n"
        "- issue_insights max 10 entries.\n"
        "Payload:\n"
        f"{json.dumps(compact_payload, separators=(',', ':'))}"
    )


def _report_analysis_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "mode",
            "hero_callout",
            "category_summary",
            "section_copy",
            "important_issues",
            "issue_insights",
            "action_plan",
        ],
        "properties": {
            "mode": {"type": "string", "enum": ["llm"]},
            "hero_callout": {"type": "string"},
            "category_summary": {"type": "string"},
            "section_copy": {
                "type": "object",
                "additionalProperties": False,
                "required": ["breakdown", "issues", "triage", "details", "actions"],
                "properties": {
                    "breakdown": {"type": "string"},
                    "issues": {"type": "string"},
                    "triage": {"type": "string"},
                    "details": {"type": "string"},
                    "actions": {"type": "string"},
                },
            },
            "important_issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "short_id",
                        "title",
                        "why_important",
                        "risk_level",
                        "confidence",
                        "next_checks",
                    ],
                    "properties": {
                        "short_id": {"type": "string"},
                        "title": {"type": "string"},
                        "why_important": {"type": "string"},
                        "risk_level": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "next_checks": {"type": "string"},
                    },
                },
            },
            "issue_insights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["short_id", "summary", "next_step", "why_important"],
                    "properties": {
                        "short_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "next_step": {"type": "string"},
                        "why_important": {"type": "string"},
                    },
                },
            },
            "action_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "body", "owner"],
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "owner": {"type": "string"},
                    },
                },
            },
        },
    }


def _compact_payload_for_llm(payload: dict[str, Any]) -> dict[str, Any]:
    categories = payload.get("categories", [])[:8]
    top_issues = payload.get("top_issues", [])[:8]
    return {
        "org": payload.get("org"),
        "project": payload.get("project"),
        "query": payload.get("query"),
        "window_start": payload.get("window_start"),
        "window_end": payload.get("window_end"),
        "totals": payload.get("totals", {}),
        "categories": categories,
        "top_issues": [
            {
                "short_id": issue.get("short_id"),
                "title": issue.get("title"),
                "category": issue.get("category"),
                "priority_hint": issue.get("priority_hint"),
                "status": issue.get("status"),
                "total_events": issue.get("total_events"),
                "events_24h": issue.get("events_24h"),
                "affected_users": issue.get("affected_users"),
                "age_days": issue.get("age_days"),
                "platform": issue.get("platform"),
            }
            for issue in top_issues
        ],
    }


def _generate_llm_analysis(
    *,
    model_name: str,
    max_tokens: int,
    payload: dict[str, Any],
    openai_api_key: str | None,
) -> dict[str, Any]:
    if not openai_api_key:
        raise ReportError("Missing OpenAI API key for LLM analysis. Set OPENAI_API_KEY or pass --openai-api-key.")

    client = OpenAI(api_key=openai_api_key)
    prompt = _build_llm_analysis_prompt(payload=payload)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sentry_report_analysis",
                    "strict": True,
                    "schema": _report_analysis_json_schema(),
                },
            },
            max_tokens=max_tokens,
            temperature=0,
        )
        content = response.choices[0].message.content
    except Exception as exc:
        raise ReportError(f"Failed to generate LLM analysis text: {exc}") from exc

    if not isinstance(content, str):
        raise ReportError("LLM analysis response is empty.")
    return _parse_llm_json_response(content)


def _merge_llm_analysis_with_automated(
    *, automated_analysis: dict[str, Any], llm_analysis: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(automated_analysis)
    merged["mode"] = "llm"

    hero_callout = _first_str(llm_analysis, ("hero_callout", "heroCallout"))
    if hero_callout:
        merged["hero_callout"] = hero_callout

    category_summary = _first_str(llm_analysis, ("category_summary", "categorySummary"))
    if category_summary:
        merged["category_summary"] = category_summary

    section_copy = llm_analysis.get("section_copy")
    if not isinstance(section_copy, dict):
        section_copy = llm_analysis.get("sectionCopy")
    if isinstance(section_copy, dict):
        current = dict(merged.get("section_copy", {}))
        aliases = {
            "breakdown": ("breakdown", "breakdown_summary", "breakdownSummary"),
            "issues": ("issues", "issues_summary", "issuesSummary"),
            "triage": ("triage", "triage_summary", "triageSummary"),
            "details": ("details", "details_summary", "detailsSummary"),
            "actions": ("actions", "actions_summary", "actionsSummary"),
        }
        for key, key_aliases in aliases.items():
            value = _first_str(section_copy, key_aliases)
            if value:
                current[key] = value
        merged["section_copy"] = current

    action_plan = llm_analysis.get("action_plan")
    if not isinstance(action_plan, list):
        action_plan = llm_analysis.get("actionPlan")
    if isinstance(action_plan, list):
        filtered_plan: list[dict[str, str]] = []
        for item in action_plan[:4]:
            if not isinstance(item, dict):
                continue
            title = _first_str(item, ("title",))
            body = _first_str(item, ("body", "description"))
            owner = _first_str(item, ("owner", "team"))
            if title and body and owner:
                filtered_plan.append({"title": title, "body": body, "owner": owner})
        if filtered_plan:
            merged["action_plan"] = filtered_plan

    important_issues = llm_analysis.get("important_issues")
    if not isinstance(important_issues, list):
        important_issues = llm_analysis.get("importantIssues")
    if isinstance(important_issues, list):
        filtered_issues: list[dict[str, str]] = []
        for item in important_issues[:5]:
            if not isinstance(item, dict):
                continue
            short_id = _first_str(item, ("short_id", "shortId", "id"))
            title = _first_str(item, ("title",))
            why_important = _first_str(item, ("why_important", "whyImportant", "reason"))
            if not (short_id and title and why_important):
                continue
            filtered_issues.append(
                {
                    "short_id": short_id,
                    "title": title,
                    "why_important": why_important,
                    "risk_level": _first_str(item, ("risk_level", "riskLevel")) or "medium",
                    "confidence": _first_str(item, ("confidence",)) or "medium",
                    "next_checks": _first_str(
                        item,
                        ("next_checks", "nextChecks", "next_checklist"),
                    )
                    or "",
                }
            )
        if filtered_issues:
            merged["important_issues"] = filtered_issues

    issue_insights = llm_analysis.get("issue_insights")
    if not isinstance(issue_insights, list):
        issue_insights = llm_analysis.get("issueInsights")
    if isinstance(issue_insights, list):
        filtered_insights: list[dict[str, str]] = []
        for item in issue_insights[:10]:
            if not isinstance(item, dict):
                continue
            short_id = _first_str(item, ("short_id", "shortId", "id"))
            if not short_id:
                continue
            insight: dict[str, str] = {"short_id": short_id}
            summary = _first_str(item, ("summary", "analysis"))
            next_step = _first_str(item, ("next_step", "nextStep", "next_action"))
            why_important = _first_str(item, ("why_important", "whyImportant", "reason"))
            if summary:
                insight["summary"] = summary
            if next_step:
                insight["next_step"] = next_step
            if why_important:
                insight["why_important"] = why_important
            if len(insight) > 1:
                filtered_insights.append(insight)
        if filtered_insights:
            merged["issue_insights"] = filtered_insights

    return merged


def _parse_llm_json_response(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    candidates = [text]

    if "```" in text:
        for part in text.split("```"):
            candidate = part.strip()
            if not candidate:
                continue
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            candidates.append(candidate)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ReportError("LLM response does not contain a valid JSON object.")


def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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

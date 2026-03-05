from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sentry_report_kit.reporting import (
    CategorySummary,
    IssueItem,
    ReportError,
    ReportPayload,
    ReportRequest,
    ReportTotals,
    _build_automated_analysis,
    _resolve_window,
    _sum_events_from_stats_payload,
    render_html,
)


def test_automated_analysis_contains_hero_text() -> None:
    totals = ReportTotals(
        total_events=100,
        total_issues=2,
        unresolved_issues=2,
        top_events_total=90,
    )
    categories = [
        CategorySummary(
            category="Backend/runtime",
            issues=2,
            total_events=100,
            total_users=3,
        )
    ]
    top_issues = [
        IssueItem(
            issue_id="1",
            short_id="RESTOKE-1",
            title="Boom",
            permalink="https://sentry.io/issues/1",
            status="unresolved",
            level="error",
            total_events=90,
            affected_users=3,
            events_24h=12,
            events_per_hour_24h=0.5,
            first_seen="2026-01-01T00:00:00Z",
            last_seen="2026-01-02T00:00:00Z",
            age_days=1,
            platform="python",
            type="Exception",
            culprit="main.task",
            file="main/task.py",
            function="run",
            category="Backend/runtime",
            priority_hint="P1",
        )
    ]

    analysis = _build_automated_analysis(
        totals=totals,
        categories=categories,
        top_issues=top_issues,
    )

    assert "Top issues drive" in analysis["hero_callout"]
    assert analysis["action_plan"]


def test_render_html_embeds_report_data_script() -> None:
    payload = ReportPayload(
        schema_version="1",
        generated_at="2026-03-05T10:00:00Z",
        org="restoke",
        project="restoke",
        query="is:unresolved",
        window_start="2026-02-01T00:00:00Z",
        window_end="2026-03-01T00:00:00Z",
        totals=ReportTotals(
            total_events=0,
            total_issues=0,
            unresolved_issues=0,
            top_events_total=0,
        ),
        categories=[],
        top_issues=[],
        category_top_issues=[],
        analysis={"hero_callout": "test", "section_copy": {}, "action_plan": []},
    )

    html = render_html(payload)

    assert 'id="report-data"' in html
    assert "restoke" in html


def test_render_html_escapes_script_terminator_in_payload() -> None:
    payload = ReportPayload(
        schema_version="1",
        generated_at="2026-03-05T10:00:00Z",
        org="restoke",
        project="restoke",
        query="is:unresolved",
        window_start="2026-02-01T00:00:00Z",
        window_end="2026-03-01T00:00:00Z",
        totals=ReportTotals(
            total_events=0,
            total_issues=0,
            unresolved_issues=0,
            top_events_total=0,
        ),
        categories=[],
        top_issues=[],
        category_top_issues=[],
        analysis={"hero_callout": "</script><script>alert(1)</script>", "section_copy": {}, "action_plan": []},
    )

    html = render_html(payload)

    assert "<\\/script>" in html


def test_resolve_window_accepts_explicit_start_end() -> None:
    request = ReportRequest(
        org="restoke",
        project="restoke",
        query="is:unresolved",
        days=None,
        start=datetime(2026, 2, 1, tzinfo=UTC),
        end=datetime(2026, 3, 1, tzinfo=UTC),
    )

    start, end = _resolve_window(request)

    assert start == datetime(2026, 2, 1, tzinfo=UTC)
    assert end == datetime(2026, 3, 1, tzinfo=UTC)


def test_resolve_window_rejects_days_with_start_end() -> None:
    request = ReportRequest(
        org="restoke",
        project="restoke",
        query="is:unresolved",
        days=30,
        start=datetime(2026, 2, 1, tzinfo=UTC),
        end=datetime(2026, 3, 1, tzinfo=UTC),
    )

    with pytest.raises(ReportError, match="--days cannot be combined"):
        _resolve_window(request)


def test_sum_events_from_stats_payload_raises_on_invalid_shape() -> None:
    with pytest.raises(ReportError, match="stats payload is not a list"):
        _sum_events_from_stats_payload({"not": "a-list"})

from __future__ import annotations

from sentry_report_kit.reporting import (
    CategorySummary,
    IssueItem,
    ReportPayload,
    ReportTotals,
    _build_automated_analysis,
    render_html,
)


def test_automated_analysis_contains_hero_text() -> None:
    totals = ReportTotals(
        total_events=100, total_issues=2, unresolved_issues=2, top_events_total=90
    )
    categories = [
        CategorySummary(
            category="Backend/runtime", issues=2, total_events=100, total_users=3
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
            issue_type="Exception",
            culprit="main.task",
            file="main/task.py",
            function="run",
            category="Backend/runtime",
            priority_hint="P1",
        )
    ]

    analysis = _build_automated_analysis(
        totals=totals, categories=categories, top_issues=top_issues
    )

    assert "Top issues drive" in analysis["hero_callout"]


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
            total_events=0, total_issues=0, unresolved_issues=0, top_events_total=0
        ),
        categories=[],
        top_issues=[],
        category_top_issues=[],
        analysis={"hero_callout": "test"},
    )

    html = render_html(payload)

    assert 'id="report-data"' in html
    assert "restoke" in html

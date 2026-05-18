#!/usr/bin/env python3
"""
Module 5 compliance dashboard for the ReguVision OTC derivatives engine.

Run from the repository root:

    python dashboard.py

The script writes a self-contained `module5_dashboard.html` next to this Python
file and opens it automatically. The dashboard reads the existing Module 3
output file and regenerates every visualisation directly from that report.
Optional supporting files (`trades.json` and `output_m2_upi_templates.json`)
enrich the labels and the classification-frontier panel.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import socket
import webbrowser
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple


STATUS_ORDER = ["COMPLIANT", "CONDITIONAL", "NONCOMPLIANT", "NOT_APPLICABLE"]
STATUS_LABELS = {
    "COMPLIANT": "COMPLIANT",
    "CONDITIONAL": "CONDITIONAL",
    "NONCOMPLIANT": "NONCOMPLIANT",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
}
STATUS_CLASS = {
    "COMPLIANT": "status-compliant",
    "CONDITIONAL": "status-conditional",
    "NONCOMPLIANT": "status-noncompliant",
    "NOT_APPLICABLE": "status-na",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def clean_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def esc(value: Any) -> str:
    return html.escape(clean_text(value), quote=True)


def status_badge(status: str) -> str:
    css_class = STATUS_CLASS.get(status, "status-unknown")
    label = STATUS_LABELS.get(status, status)
    return f'<span class="status-pill {css_class}">{esc(label)}</span>'


def classify_finding(finding: str) -> Tuple[str, str, str]:
    text = finding.strip()
    lower = text.lower()
    rules = [
        (r"reporting counterparty lei|reporting lei", "LEI validation", "reporting_counterparty_lei"),
        (r"other counterparty lei|other lei", "LEI validation", "other_counterparty_lei"),
        (r"\buti\b|namespace", "UTI validation", "uti"),
        (r"\bupi\b", "UPI/product taxonomy", "upi"),
        (r"product definition", "UPI/product taxonomy", "product_definition"),
        (r"currency", "Reference data", "notional_currency"),
        (r"reference_rate_term_unit|reference rate term unit", "Reference data", "reference_rate_term_unit"),
        (r"reference[_ ]rate", "Reference data", "reference_rate"),
        (r"delivery_type", "Reference data", "delivery_type"),
        (r"portfolio code|collateral_portfolio_code", "EMIR collateral fields", "collateral_portfolio_code"),
        (r"initial_margin_posted", "EMIR margin fields", "initial_margin_posted"),
        (r"variation_margin_posted", "EMIR margin fields", "variation_margin_posted"),
        (r"maturity_date", "Date logic", "maturity_date"),
        (r"effective_date", "Date logic", "effective_date"),
        (r"notional", "Economic terms", "notional_amount"),
        (r"platform|cftc dcm", "Venue classification", "platform_type"),
        (r"cleared", "Clearing fields", "cleared"),
        (r"action_type", "Lifecycle fields", "action_type"),
    ]
    for pattern, category, field in rules:
        if re.search(pattern, lower):
            return category, field, text
    return "Other data-quality issue", "other_field", text


def collect_regimes(report: List[Dict[str, Any]]) -> List[str]:
    regimes: List[str] = []
    for item in report:
        for regime in item.get("regime_compliance", {}):
            if regime not in regimes:
                regimes.append(regime)
    return regimes or ["CFTC", "EMIR"]


def trade_sort_key(trade_id: str) -> Tuple[str, int]:
    match = re.match(r"([A-Za-z]+)(\d+)$", trade_id)
    if not match:
        return trade_id, 0
    return match.group(1), int(match.group(2))


def build_dashboard_model(base_dir: Path, report_name: str, trades_name: str, m2_name: str) -> Dict[str, Any]:
    report_path = base_dir / report_name
    trades_path = base_dir / trades_name
    m2_path = base_dir / m2_name

    report = load_json(report_path, [])
    trades = load_json(trades_path, [])
    m2_results = load_json(m2_path, [])

    if not isinstance(report, list) or not report:
        raise FileNotFoundError(
            f"Could not load a non-empty Module 3 report from {report_path}. "
            "Run run_compliance_check.py first or pass --report."
        )

    trade_map = {item.get("trade_id"): item for item in trades if isinstance(item, dict)}
    m2_map = {item.get("trade_id"): item for item in m2_results if isinstance(item, dict)}
    regimes = collect_regimes(report)

    rows = []
    status_totals: Counter[str] = Counter()
    asymmetry_count = 0
    error_counter: Counter[str] = Counter()
    error_field_counter: Dict[str, Counter[str]] = defaultdict(Counter)
    error_examples: Dict[Tuple[str, str], str] = {}
    asset_counts: Dict[str, Dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))

    sorted_report = sorted(report, key=lambda item: trade_sort_key(clean_text(item.get("trade_id"))))

    for item in sorted_report:
        trade_id = clean_text(item.get("trade_id"))
        raw_trade = trade_map.get(trade_id, {})
        raw_asset_class = clean_text(raw_trade.get("asset_class"), "Unknown")
        asset_class = raw_asset_class
        use_case = clean_text(raw_trade.get("use_case"), "Unknown")
        platform = clean_text(raw_trade.get("platform"), raw_trade.get("platform_type", ""))
        m2_item = m2_map.get(trade_id, {})
        row_statuses: Dict[str, str] = {}
        row_findings: Dict[str, List[str]] = {}
        trade_error_fields = set()

        for regime in regimes:
            regime_block = item.get("regime_compliance", {}).get(regime, {})
            status = clean_text(regime_block.get("status"), "UNKNOWN")
            findings = list(regime_block.get("findings") or [])
            row_statuses[regime] = status
            row_findings[regime] = findings
            status_totals[status] += 1
            asset_counts[asset_class][regime][status] += 1
            for finding in findings:
                category, field, example = classify_finding(clean_text(finding))
                trade_error_fields.add((category, field))
                error_examples.setdefault((category, field), example)

        for category, field in trade_error_fields:
            error_counter[category] += 1
            error_field_counter[category][field] += 1

        if clean_text(item.get("overall_compliance")) == "ASYMMETRY":
            asymmetry_count += 1

        rows.append(
            {
                "trade_id": trade_id,
                "asset_class": asset_class,
                "raw_asset_class": raw_asset_class,
                "instrument_type": clean_text(raw_trade.get("instrument_type"), "Unknown"),
                "use_case": use_case,
                "platform": platform,
                "statuses": row_statuses,
                "findings": row_findings,
                "lei_validation": clean_text(item.get("lei_validation")),
                "uti_validation": clean_text(item.get("uti_validation")),
                "overall_compliance": clean_text(item.get("overall_compliance")),
                "m2_status": clean_text(m2_item.get("status")),
                "classification_note": clean_text(m2_item.get("classification_note")),
                "event_description": clean_text(raw_trade.get("event_description")),
                "exposure": clean_text(raw_trade.get("underlying_economic_exposure")),
            }
        )

    asset_breakdown = []
    for asset_class in sorted(asset_counts):
        for regime in regimes:
            counts = asset_counts[asset_class][regime]
            applicable = sum(count for status, count in counts.items() if status != "NOT_APPLICABLE")
            compliant = counts["COMPLIANT"]
            clean_rate = (compliant / applicable * 100) if applicable else 0.0
            asset_breakdown.append(
                {
                    "asset_class": asset_class,
                    "regime": regime,
                    "clean_rate": clean_rate,
                    "applicable": applicable,
                    "total": sum(counts.values()),
                    "counts": {status: counts[status] for status in STATUS_ORDER},
                }
            )

    error_rows = []
    for category, count in error_counter.most_common():
        field_rows = [
            {
                "field": field,
                "count": field_count,
                "example": error_examples.get((category, field), ""),
            }
            for field, field_count in error_field_counter[category].most_common()
        ]
        error_rows.append({"label": category, "count": count, "fields": field_rows})

    frontier_rows = [row for row in rows if row["trade_id"] in {"T026", "T027", "T028"}]
    frontier_rows = sorted(frontier_rows, key=lambda row: trade_sort_key(row["trade_id"]))

    total_regime_checks = len(rows) * len(regimes)
    compliant_checks = status_totals["COMPLIANT"]
    conditional_checks = status_totals["CONDITIONAL"]
    noncompliant_checks = status_totals["NONCOMPLIANT"]
    not_applicable_checks = status_totals["NOT_APPLICABLE"]
    fully_compliant_trades = sum(
        1
        for row in rows
        if all(row["statuses"].get(regime) == "COMPLIANT" for regime in regimes)
    )
    top_error = error_rows[0]["label"] if error_rows else "No recurring finding"
    top_error_count = error_rows[0]["count"] if error_rows else 0

    return {
        "report_path": report_path,
        "trades_path": trades_path,
        "m2_path": m2_path,
        "regimes": regimes,
        "rows": rows,
        "asset_breakdown": asset_breakdown,
        "error_rows": error_rows,
        "frontier_rows": frontier_rows,
        "summary": {
            "trade_count": len(rows),
            "regime_count": len(regimes),
            "total_regime_checks": total_regime_checks,
            "compliant_checks": compliant_checks,
            "conditional_checks": conditional_checks,
            "noncompliant_checks": noncompliant_checks,
            "not_applicable_checks": not_applicable_checks,
            "asymmetry_count": asymmetry_count,
            "fully_compliant_trades": fully_compliant_trades,
            "top_error": top_error,
            "top_error_count": top_error_count,
        },
    }


def render_heatmap(rows: List[Dict[str, Any]], regimes: List[str]) -> str:
    header = "".join(f"<th>{esc(regime)}</th>" for regime in regimes)
    body = []
    for row in rows:
        cells = []
        for regime in regimes:
            status = row["statuses"].get(regime, "UNKNOWN")
            findings = row["findings"].get(regime, [])
            title = "; ".join(findings) if findings else "No findings"
            cells.append(
                '<td class="heat-cell {css}" title="{title}">'
                '<span>{label}</span>'
                "</td>".format(
                    css=STATUS_CLASS.get(status, "status-unknown"),
                    title=esc(title),
                    label=esc(STATUS_LABELS.get(status, status)),
                )
            )
        body.append(
            "<tr>"
            f'<th class="trade-label">{esc(row["trade_id"])}'
            f'<small>{esc(row["asset_class"])}</small></th>'
            + "".join(cells)
            + "</tr>"
        )
    return (
        '<div class="heatmap-scroll"><table class="heatmap">'
        "<thead><tr><th>Trade</th>"
        + header
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def render_error_chart(error_rows: List[Dict[str, Any]]) -> str:
    if not error_rows:
        return '<p class="empty">No compliance findings were present in the report.</p>'
    max_count = max(row["count"] for row in error_rows) or 1
    bars = []
    for row in error_rows[:10]:
        width = row["count"] / max_count * 100
        field_details = []
        for field in row.get("fields", [])[:4]:
            field_details.append(
                f'<span><strong>{esc(field["field"])}</strong>: {field["count"]}</span>'
            )
        details = " ".join(field_details)
        bars.append(
            '<div class="bar-row">'
            f'<div class="bar-label">{esc(row["label"])}</div>'
            '<div class="bar-track">'
            f'<div class="bar-fill" style="width:{width:.2f}%"></div>'
            "</div>"
            f'<div class="bar-value">{row["count"]}</div>'
            f'<div class="bar-example">{details}</div>'
            "</div>"
        )
    return '<div class="bar-chart">' + "".join(bars) + "</div>"


def render_asset_breakdown(asset_breakdown: List[Dict[str, Any]], regimes: List[str]) -> str:
    if not asset_breakdown:
        return '<p class="empty">No asset-class data was available.</p>'
    rows = []
    for item in asset_breakdown:
        clean_width = item["clean_rate"]
        counts = item["counts"]
        rows.append(
            "<tr>"
            f"<td>{esc(item['asset_class'])}</td>"
            f"<td>{esc(item['regime'])}</td>"
            '<td class="rate-cell">'
            '<div class="rate-track">'
            f'<span class="rate-fill clean-fill" style="width:{clean_width:.2f}%"></span>'
            "</div>"
            f"<strong>{item['clean_rate']:.1f}%</strong>"
            "</td>"
            f"<td>{item['applicable']}</td>"
            f"<td>{counts['COMPLIANT']} / {counts['CONDITIONAL']} / {counts['NONCOMPLIANT']} / {counts['NOT_APPLICABLE']}</td>"
            "</tr>"
        )
    return (
        '<table class="breakdown-table"><thead><tr>'
        "<th>Asset class</th><th>Regime</th><th>Clean compliance rate</th>"
        "<th>Applicable checks</th>"
        "<th>COMPLIANT / CONDITIONAL / NONCOMPLIANT / NOT_APPLICABLE</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_frontier(frontier_rows: List[Dict[str, Any]], regimes: List[str]) -> str:
    if not frontier_rows:
        return '<p class="empty">Trades T026 to T028 were not found in the report.</p>'
    regime_headers = "".join(f"<th>{esc(regime)}</th>" for regime in regimes)
    rows = []
    for row in frontier_rows:
        status_cells = "".join(
            f"<td>{status_badge(row['statuses'].get(regime, 'UNKNOWN'))}</td>" for regime in regimes
        )
        findings = []
        for regime in regimes:
            for finding in row["findings"].get(regime, []):
                findings.append(f"{regime}: {finding}")
        note_parts = [
            row["classification_note"] or "No ANNA-DSB classification note was provided.",
            "; ".join(findings) if findings else "No regime findings.",
        ]
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row['trade_id'])}</strong><small>{esc(row['use_case'])}</small></td>"
            f"<td>{esc(row['platform'])}</td>"
            + status_cells
            + f"<td>{esc(' | '.join(note_parts))}</td>"
            "</tr>"
        )
    return (
        '<table class="frontier-table"><thead><tr>'
        "<th>Trade</th><th>Venue/platform</th>"
        + regime_headers
        + "<th>Compliance note text</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_interpretation(model: Dict[str, Any]) -> str:
    summary = model["summary"]
    frontier = model["frontier_rows"]
    frontier_ids = ", ".join(row["trade_id"] for row in frontier) or "T026 to T028"
    return (
        "<p>"
        f"The heatmap is the primary audit view: each row is one trade and each cell is "
        f"that trade's status under {', '.join(esc(regime) for regime in model['regimes'])}. "
        f"Only <strong>{summary['fully_compliant_trades']}</strong> trade is fully COMPLIANT "
        "across both regimes; the rest are blocked by identifier, UPI, margin, collateral, "
        "or taxonomy findings. This avoids treating two regime-level COMPLIANT cells as "
        "two separate clean trades."
        "</p>"
        "<p>"
        f"The error-frequency chart first groups findings into broad remediation themes, "
        "then lists the specific failing fields inside each theme. A field is counted "
        "once per trade even if both CFTC and EMIR report the same defect, but different "
        "fields on the same trade are all counted. The leading theme is "
        f"<strong>{esc(summary['top_error'])}</strong>, appearing across "
        f"<strong>{summary['top_error_count']}</strong> trade-field failures."
        "</p>"
        "<p>"
        f"The classification-frontier panel isolates {esc(frontier_ids)} because those "
        "trades are not just failed validations. Kalshi-style contracts on a CFTC-regulated "
        "DCM are treated as conditional in the US but outside EMIR reporting, while the "
        "decentralised blockchain venue is outside both reporting stacks. The embedded "
        "classification note makes the core policy problem explicit: the absence of an "
        "ANNA-DSB product definition is itself a visibility risk, because the engine cannot "
        "route, aggregate, or report activity that the taxonomy has no place to describe."
        "</p>"
    )


def render_dashboard(model: Dict[str, Any]) -> str:
    heatmap = render_heatmap(model["rows"], model["regimes"])
    error_chart = render_error_chart(model["error_rows"])
    asset_breakdown = render_asset_breakdown(model["asset_breakdown"], model["regimes"])
    frontier = render_frontier(model["frontier_rows"], model["regimes"])
    interpretation = render_interpretation(model)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Module 5 Compliance Dashboard</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --surface: #ffffff;
      --ink: #172033;
      --muted: #66758f;
      --line: #d8e0ec;
      --navy: #12345b;
      --green: #1f8a5b;
      --amber: #ba7a12;
      --red: #bf3f3f;
      --gray: #7b8798;
      --teal: #168189;
      --blue: #2f67b1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      line-height: 1.5;
    }}
    header {{
      background: #10233e;
      color: #fff;
      padding: 28px 32px 22px;
      border-bottom: 4px solid var(--teal);
    }}
    header h1 {{
      margin: 0;
      font-size: 28px;
      letter-spacing: 0;
    }}
    main {{
      width: min(1280px, calc(100% - 32px));
      margin: 24px auto 48px;
    }}
    section {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      margin-top: 16px;
    }}
    section h2 {{
      margin: 0 0 6px;
      font-size: 19px;
      letter-spacing: 0;
    }}
    section .subhead {{
      margin: 0 0 16px;
      color: var(--muted);
      font-size: 14px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0 14px;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .status-compliant {{ background: var(--green); }}
    .status-conditional {{ background: var(--amber); }}
    .status-noncompliant {{ background: var(--red); }}
    .status-na {{ background: var(--gray); }}
    .status-unknown {{ background: #374151; }}
    .heatmap-scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }}
    thead th {{
      background: #eef3f8;
      color: #2b3950;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    tbody tr:last-child td, tbody tr:last-child th {{ border-bottom: 0; }}
    .trade-label {{
      position: sticky;
      left: 0;
      background: #fff;
      z-index: 1;
      width: 120px;
      min-width: 120px;
    }}
    .trade-label small, .frontier-table small {{
      display: block;
      color: var(--muted);
      margin-top: 2px;
      font-weight: 500;
    }}
    .heat-cell {{
      width: calc((100% - 120px) / 2);
      color: #fff;
      font-weight: 700;
      text-align: center;
    }}
    .heatmap {{
      table-layout: fixed;
      min-width: 520px;
    }}
    .heatmap thead th {{
      text-align: center;
    }}
    .heatmap thead th:first-child {{
      width: 120px;
      text-align: left;
    }}
    .heat-cell span {{ display: block; }}
    .bar-chart {{ display: grid; gap: 12px; }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(150px, 210px) 1fr 48px;
      gap: 10px;
      align-items: center;
    }}
    .bar-label {{ font-weight: 700; }}
    .bar-track, .rate-track {{
      position: relative;
      min-height: 26px;
      background: #e8edf4;
      border-radius: 6px;
      overflow: hidden;
    }}
    .bar-fill {{
      position: absolute;
      inset: 0 auto 0 0;
      background: var(--blue);
    }}
    .bar-value {{
      font-weight: 800;
      text-align: right;
    }}
    .bar-example {{
      grid-column: 2 / 4;
      color: var(--muted);
      font-size: 12px;
      margin-top: -6px;
    }}
    .bar-example span {{
      display: inline-block;
      margin-right: 12px;
      white-space: nowrap;
    }}
    .breakdown-table .rate-cell {{
      display: grid;
      grid-template-columns: 1fr 64px;
      gap: 10px;
      align-items: center;
      min-width: 220px;
    }}
    .rate-fill {{
      position: absolute;
      inset: 0 auto 0 0;
      display: block;
    }}
    .clean-fill {{ background: var(--green); }}
    .frontier-table td:last-child {{ min-width: 360px; }}
    .interpretation p {{
      max-width: 1080px;
      margin: 0 0 14px;
    }}
    .interpretation p:last-child {{ margin-bottom: 0; }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 8px;
    }}
    .empty {{
      margin: 0;
      color: var(--muted);
    }}
    @media (max-width: 900px) {{
      header {{ padding: 22px 18px; }}
      main {{ width: min(100% - 20px, 1280px); }}
      .bar-row {{ grid-template-columns: 1fr 48px; }}
      .bar-label, .bar-track {{ grid-column: 1 / 2; }}
      .bar-example {{ grid-column: 1 / 3; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Module 5 Compliance Dashboard</h1>
  </header>
  <main>
    <section>
      <h2>Portfolio Compliance Heatmap</h2>
      <p class="subhead">Rows are trade IDs, columns are regimes, and cells are colour-coded by compliance status.</p>
      <div class="legend">
        {status_badge('COMPLIANT')}
        {status_badge('CONDITIONAL')}
        {status_badge('NONCOMPLIANT')}
        {status_badge('NOT_APPLICABLE')}
      </div>
      {heatmap}
    </section>

    <section>
      <h2>Error Frequency Chart</h2>
      <p class="subhead">Horizontal bar chart of the most common failure themes, with the concrete fields listed below each bar. A trade can contribute to multiple fields; the same field is counted once per trade.</p>
      {error_chart}
    </section>

    <section>
      <h2>Asset Class Breakdown</h2>
      <p class="subhead">Clean compliance rate by asset class and regime. Conditional and not-applicable cases remain visible in the status-count column.</p>
      {asset_breakdown}
    </section>

    <section>
      <h2>Classification Frontier Panel</h2>
      <p class="subhead">Dedicated view of T026 to T028 showing jurisdictional asymmetry and the exact compliance note text.</p>
      {frontier}
    </section>

    <section class="interpretation">
      <h2>Interpretation</h2>
      {interpretation}
    </section>
  </main>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    model_args: Dict[str, Any] = {}

    def do_GET(self) -> None:
        self._serve_dashboard(include_body=True)

    def do_HEAD(self) -> None:
        self._serve_dashboard(include_body=False)

    def _serve_dashboard(self, include_body: bool) -> None:
        if self.path not in {"/", "/index.html"}:
            self.send_error(404, "Only / is served by the Module 5 dashboard")
            return
        try:
            model = build_dashboard_model(**self.model_args)
            body = render_dashboard(model).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if include_body:
                self.wfile.write(body)
        except Exception as exc:  # pragma: no cover - visible in browser/server log
            message = f"Dashboard generation failed: {exc}"
            body = message.encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if include_body:
                self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} - {format % args}")


def choose_port(host: str, requested_port: int) -> int:
    if requested_port:
        return requested_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def export_html(path: Path, model_args: Dict[str, Any]) -> None:
    model = build_dashboard_model(**model_args)
    path.write_text(render_dashboard(model), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Module 5 compliance dashboard HTML file.")
    parser.add_argument("--report", default="output_m3_final_report.json", help="Module 3 JSON report file")
    parser.add_argument("--trades", default="trades.json", help="Raw trades JSON file")
    parser.add_argument("--m2", default="output_m2_upi_templates.json", help="Module 2 UPI output JSON file")
    parser.add_argument("--output", default="module5_dashboard.html", help="HTML file to write next to dashboard.py")
    parser.add_argument("--serve", action="store_true", help="Start a local preview server instead of only writing HTML")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the optional preview server")
    parser.add_argument("--port", type=int, default=0, help="Preview server port. Defaults to an available port.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the generated HTML file automatically")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    model_args = {
        "base_dir": base_dir,
        "report_name": args.report,
        "trades_name": args.trades,
        "m2_name": args.m2,
    }

    output_path = (base_dir / args.output).resolve()
    export_html(output_path, model_args)
    print(f"Saved Module 5 dashboard HTML to {output_path}")
    if not args.no_open:
        webbrowser.open(output_path.as_uri())

    if not args.serve:
        return

    port = choose_port(args.host, args.port)
    DashboardHandler.model_args = model_args
    server = ThreadingHTTPServer((args.host, port), DashboardHandler)
    url = f"http://{args.host}:{port}/"
    print("Module 5 compliance dashboard is running.")
    print(f"Open {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

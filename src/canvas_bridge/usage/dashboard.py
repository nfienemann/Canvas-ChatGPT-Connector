"""Local aggregate operator report; no remote resources, scripts or student route."""

import html


def value(item):
    return html.escape("N/A" if item is None else str(item))


def table(headers, rows):
    return (
        "<table><thead><tr>"
        + "".join(f"<th scope=col>{value(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{value(c)}</td>" for c in row) + "</tr>" for row in rows)
        + "</tbody></table>"
    )


def render(report):
    cards = "".join(
        f"<article><span>{label}</span><strong>{value(report.get(key))}</strong></article>"
        for key, label in (
            ("usable", "Usable units"),
            ("settled", "Settled estimate"),
            ("reserved", "In flight"),
            ("uncertain", "Uncertain holds"),
            ("external", "External estimate"),
            ("available", "Available units"),
        )
    )
    pools = table(
        ("Workload pool", "Target", "Booked", "Borrowed"),
        (
            [p.get(k) for k in ("name", "target", "booked", "borrowed")]
            for p in report.get("pools", [])
        ),
    )
    operations = table(
        ("Operation", "Attempts", "Estimated commercial units", "Technical cost"),
        (
            [p.get(k) for k in ("operation", "attempts", "estimated_units", "technical_cost")]
            for p in report.get("operations", [])
        ),
    )
    signals = table(("Signal", "Count"), sorted(report.get("events", {}).items()))
    billing = table(
        ("Measure", "Value"),
        (
            ("Included allowance", report.get("included_allowance")),
            ("Safety margin (%)", report.get("safety_margin_pct")),
            ("Protected reserve remaining", report.get("reserve_remaining")),
            ("Vendor reported units", report.get("vendor_total")),
            ("Vendor difference from local estimate", report.get("vendor_difference_from_local")),
            ("Vendor spend", report.get("vendor_spend", "N/A")),
            ("Cache hit rate (eligible reads)", report.get("eligible_cache_hit_rate")),
            ("Requests saved by coalescing", report.get("coalesced_requests_saved")),
            (
                "Estimated runway, 7-day rate (days)",
                report.get("runway_days_estimate", {}).get("7"),
            ),
            (
                "Estimated runway, 30-day rate (days)",
                report.get("runway_days_estimate", {}).get("30"),
            ),
        ),
    )
    status = (
        "Accounting exception — network admission paused"
        if report.get("quarantined") or report.get("contract_quarantined")
        else "Local admission accounting"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>Upstream usage — Operator report</title>"
        "<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:1rem;background:#f4f7fa;color:#172438}h1{margin-bottom:.2rem}h2{margin-top:2rem}section.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem}article{background:white;border:1px solid #ccd4de;border-radius:8px;padding:1rem}article span{display:block;color:#41536a}strong{display:block;font-size:1.8rem}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:.7rem;border-bottom:1px solid #d7dee8;overflow-wrap:anywhere}th{background:#e6edf5}.note{color:#41536a}footer{margin-top:2rem}</style></head><body>"
        f"<h1>Upstream usage</h1><p>{value(status)}</p><p class=note>Provider: {value(report.get('provider'))} · Policy version: {value(report.get('policy_version'))}</p>"
        f"<p>Period: {value(report.get('period_start'))} to {value(report.get('period_end'))} · {value(report.get('cycle_timezone'))}</p>"
        '<section class=cards aria-label="Commercial unit accounting">' + cards + "</section>"
        "<h2>Workload allocation</h2>"
        + pools
        + "<h2>Reconciliation and efficiency</h2>"
        + billing
        + "<h2>Operation classes</h2><p class=note>Technical request cost is separate from commercial units.</p>"
        + operations
        + "<h2>Alerts and admission signals</h2>"
        + signals
        + "<footer class=note>Local estimates do not guarantee vendor invoice totals. Runway is an estimate. Missing spend is N/A. This report contains no student records and grants no provider access.</footer></body></html>"
    )

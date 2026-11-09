"""Static transport inventory and source-bound compliance evidence, never approvals."""

import ast

INVENTORY = {
    "canvas.py": "Reviewed GET routes, identity probes, pagination and retries -> GuardedHTTP -> governed_send",
    "file_download.py": "Each authorized download/redirect hop -> GuardedHTTP -> governed_send",
    "linking.py": "OAuth exchange/refresh, profile verification and credential cleanup -> governed_send",
    "personal.py": "Owner-only identity probe -> bound CanvasClient -> governed_send",
    "jobs.py": "Opt-in refresh jobs inherit durable task lineage and scheduled_sync class",
    "providers/canvas.py": "Provider facade delegates to existing authorized service clients",
    "auth.py": "Identity-provider JWKS only; infrastructure pacing, outside institution transaction agreement",
    "settings_ui.py": "Identity-provider sign-in exchange only; exact configured infrastructure endpoint",
    "cli.py": "MCP self-test client only, not an upstream Canvas client",
    "synthetic.py": "In-process .invalid MockTransport fixtures; no external traffic",
}
HTTP_IMPORTS = {
    "auth.py",
    "canvas.py",
    "cli.py",
    "file_download.py",
    "linking.py",
    "network.py",
    "synthetic.py",
    "usage/transport.py",
}


def audit(root):
    violations = []
    for path in (root / "src/canvas_bridge").rglob("*.py"):
        name = path.relative_to(root / "src/canvas_bridge").as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imports = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in imports:
                if module.split(".")[0] in {
                    "httpx",
                    "httpcore",
                    "requests",
                    "aiohttp",
                } or module.startswith("urllib.request"):
                    if name not in HTTP_IMPORTS:
                        violations.append(name + ":unreviewed_http_import")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "infrastructure_http"
                and name not in {"auth.py", "settings_ui.py"}
            ):
                violations.append(name + ":unreviewed_infrastructure_exemption")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "GuardedHTTP"
                and name != "network.py"
            ):
                if not any(k.arg == "usage" for k in node.keywords) and name != "canvas.py":
                    violations.append(name + ":missing_usage_binding")
    return sorted(set(violations))


def section(root, source, tests):
    from canvas_bridge.compliance.inventory import test_index

    required = {n for n in test_index(root) if n.startswith("tests/test_usage_")}
    cases = tests.get("cases", {})
    passed = (
        bool(required)
        and tests["status"] == "PASSED"
        and all(
            cases.get(n, {}).get("passed", 0) > 0
            and not any(cases.get(n, {}).get(k, 0) for k in ("failed", "error", "skipped"))
            for n in required
        )
    )
    violations = audit(root)
    return {
        "status": "TESTED" if passed and not violations else "IMPLEMENTED_UNVERIFIED",
        "commit": source.commit,
        "migration_revision": "f17a6b204c31",
        "policy_contract_versions": "not_inspected_private_operator_configuration",
        "technical_algorithm": "durable token concurrency/cooldown/circuit plus bounded process dispatch",
        "ledger_atomicity": "PostgreSQL singleton FOR UPDATE; SQLite BEGIN IMMEDIATE; no external calls inside transactions",
        "test_identities": sorted(required),
        "api_gate_inventory": INVENTORY,
        "release_blocking_findings": violations,
        "technical_metric": "X-Request-Cost; never commercial units",
        "financial_metric": "verified contract adapter units; local ceiling only",
        "approved_provider_list": [],
        "external_approval": "REQUIRES_EXTERNAL_APPROVAL",
        "unresolved_billing_assumptions": [
            "No real signed allowance or counting model inspected",
            "No real vendor reconciliation or deployment acceptance",
        ],
        "rollback": "Signed new policy version; preserve ledger. Restores hold all provider access until verified final statements resolve every cycle.",
    }

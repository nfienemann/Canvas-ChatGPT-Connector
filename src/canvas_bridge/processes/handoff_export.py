"""A portable human-readable projection of the already privacy-reviewed packet."""

import re
from html import escape


def text(value):
    if value is None:
        return "Unspecified"
    value = escape(" ".join(str(value).split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+!|~])", r"\\\1", value)


def markdown(shared):
    role = shared["responsibility"]
    members = {m["member_id"]: m["label"] for m in role["members"]}
    action = shared["action"]
    report = shared["assessment"]

    def person(key):
        return text(members.get(key, key))

    lines = [
        "# Artifact handoff",
        "",
        f"**Next action** — {text(shared['next_step'])}",
        "",
        f"{person(action['owner_id'])} owns the requested action. Expected output: {text(action['expected_output'])}.",
        f"Contributor: {person(role['responsible_actor'])}. Intended recipients: {', '.join(person(k) for k in role['recipient_ids']) or 'Unresolved'}.",
        "",
        "## Artifact and evidence",
        "",
        f"{text(report.get('filename') or report['logical_artifact_id'])} · {text(report['artifact_readiness'])}",
        f"Document ID: {text(report.get('document_id'))}. Content version: {text(report.get('artifact_version'))}.",
        "",
    ]
    for row in report["criteria"]:
        lines.append(
            f"- **{text(row['requirement_id'])}** · {text(row['assessment_status'])} — {text(row['criterion'])}"
        )
        for evidence in row.get("evidence", []):
            if evidence["source"] == report["logical_artifact_id"]:
                lines.append(
                    f"  - Part {evidence['part']} ({text(evidence['surface'])}): {text(evidence['quote'])}"
                )
        if row.get("next_step") and row["assessment_status"] != "satisfied":
            lines.append(f"  - Follow-up: {text(row['next_step'])}")
    lines.extend(
        [
            "",
            "## Conditions and responses",
            "",
            f"Requested action: {text(shared['next_action_state'])}. Delivery: {text(shared['delivery_state'])}.",
        ]
    )
    for b in shared["process_context"]["blockers"]:
        lines.append(f"- {text(b['scope'])} · {text(b['state'])} — {text(b['next_action'])}")
    for member in shared["ack_by_member"]:
        lines.append(f"- {person(member['member_id'])}: {text(member['state'])}")
    if shared.get("presentation_note"):
        lines.extend(["", text(shared["presentation_note"])])
    lines.extend(
        [
            "",
            f"Packet {text(shared['packet_id'])}, revision {shared['packet_revision']}. Semantic basis {text(shared['semantic_basis_id'])}.",
        ]
    )
    return "\n".join(lines) + "\n"

"""Opt-in discussion evidence in existing inventory/audit and selected planning.

Evidence is request-local and never stored in assignment snapshots. Canonical
obligations remain singular; their initial/reply stages stay attached to them.
"""

import asyncio

from canvas_bridge.discussions import (
    NOTICE,
    DiscussionCoverage,
    Participation,
    discussion_request,
    list_discussions,
)
from canvas_bridge.domain import DomainError, utcnow


def unknown(reason):
    return Participation(
        state="unavailable",
        initial_post_state="unavailable",
        additional_replies_state="unavailable",
        coverage=DiscussionCoverage(partial_reasons=[reason]),
        fetched_at=utcnow(),
        confidence="not_scanned",
    ).model_dump(mode="json", exclude={"entries"})


async def scan_topics(bridge, owner, ref, course_id, topic_ids):
    ids = list(dict.fromkeys(topic_ids))
    limit = bridge.settings.discussion_max_topics
    output = {tid: {"participation": unknown("topic_limit")} for tid in ids}
    sources = []
    semaphore = asyncio.Semaphore(bridge.settings.discussion_concurrency)

    async def one(tid):
        async with semaphore:
            try:
                result = await discussion_request(
                    bridge, owner, ref, course_id, tid, participation_only=True
                )
            except DomainError as exc:
                if exc.upstream_http_status is None:
                    raise
                output[tid] = {"participation": unknown("topic_unavailable_or_restricted")}
                return
            data = result.data
            data["participation"].pop("entries", None)
            data["topic"].pop("prompt_text", None)
            data["topic"].pop("attachments", None)
            output[tid] = {"topic": data["topic"], "participation": data["participation"]}
            sources.extend(result.sources)

    tasks = []
    try:
        async with asyncio.timeout(bridge.settings.discussion_budget_seconds):
            tasks = [asyncio.create_task(one(tid)) for tid in ids[:limit]]
            await asyncio.gather(*tasks)
    except TimeoutError:
        for tid in ids[:limit]:
            if output[tid]["participation"]["coverage"]["partial_reasons"] == ["topic_limit"]:
                output[tid] = {"participation": unknown("request_timeout")}
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return output, sources


async def enrich_obligations(bridge, owner, ref, course_id, items):
    aliases = [
        a
        for item in items
        for a in item["source_aliases"]
        if a["source_type"] == "discussion_topics" and a.get("topic_id")
    ]
    reports, sources = await scan_topics(
        bridge, owner, ref, course_id, [a["topic_id"] for a in aliases]
    )
    for item in items:
        reports_for_item = [
            reports[a["topic_id"]] for a in item["source_aliases"] if a.get("topic_id") in reports
        ]
        if reports_for_item:
            item["discussion_evidence"] = reports_for_item
            item["discussion_completion"] = "not_assessed"
    return sources


async def discussion_audit(bridge, owner, ref, course_id, assignments):
    listing = await list_discussions(
        bridge, owner, ref, course_id, include_archived=True, limit=100
    )
    topics = listing.data["topics"]
    reports, sources = await scan_topics(
        bridge, owner, ref, course_id, [t["topic_id"] for t in topics]
    )
    findings = []
    for topic in topics:
        evidence = reports[topic["topic_id"]]
        current = evidence.get("topic", topic)
        participation = evidence["participation"]
        assignment_id = topic.get("assignment_id")
        matched = (
            next(
                (
                    a
                    for a in assignments
                    if a.get("source", {})
                    .get("url", "")
                    .endswith("/assignments/" + str(assignment_id))
                ),
                None,
            )
            if assignment_id
            else None
        )
        if assignment_id and matched is None:
            findings.append(
                {
                    "kind": "discussion_assignment_not_in_inventory",
                    "topic_id": topic["topic_id"],
                    "certainty": "bounded_inventory_only",
                    "impact": "A linked assignment is absent from the retrieved inventory; visibility or coverage may explain it.",
                }
            )
        if (
            matched
            and matched.get("submission_state") in {"submitted", "resubmitted"}
            and not participation["coverage"]["complete"]
        ):
            findings.append(
                {
                    "kind": "discussion_completion_needs_investigation",
                    "topic_id": topic["topic_id"],
                    "certainty": "incomplete_evidence",
                    "impact": "Assignment submission state and incomplete thread evidence cannot establish missing participation or completed reply requirements.",
                }
            )
        for warning in current.get("deadline_warnings", []):
            if warning.startswith("conflicting"):
                findings.append(
                    {
                        "kind": "discussion_deadline_conflict",
                        "topic_id": topic["topic_id"],
                        "certainty": "needs_review",
                        "impact": warning,
                    }
                )
        if current.get("replies_due_at"):
            findings.append(
                {
                    "kind": "separate_discussion_reply_deadline",
                    "topic_id": topic["topic_id"],
                    "certainty": "source_fact",
                    "impact": "Keep the reply deadline distinct from the initial post and assignment due date.",
                }
            )
        if not participation["coverage"]["complete"]:
            findings.append(
                {
                    "kind": "discussion_participation_not_fully_verified",
                    "topic_id": topic["topic_id"],
                    "certainty": "incomplete_evidence",
                    "impact": "Investigate before calling this missing or completed work.",
                }
            )
        if not topic.get("assignment_id"):
            findings.append(
                {
                    "kind": "discussion_outside_assignment_inventory",
                    "topic_id": topic["topic_id"],
                    "certainty": "candidate_only",
                    "impact": "Use the course obligation inventory; visibility does not establish required participation.",
                }
            )
    coverage = dict(listing.data["coverage"])
    if any(not r["participation"]["coverage"]["complete"] for r in reports.values()):
        coverage["complete"] = False
        coverage["partial_reasons"] = sorted(
            set(coverage["partial_reasons"] + ["topic_scans_incomplete"])
        )
    return {
        "topics": [{"topic_id": t["topic_id"], **reports[t["topic_id"]]} for t in topics],
        "coverage": coverage,
        "topic_discovery_coverage": listing.data["coverage"],
        "findings": findings,
        "limitations": [
            NOTICE,
            "Only bounded discovered topics were scanned; inspect each topic's coverage.",
        ],
    }, sources + listing.sources

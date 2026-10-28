"""Bounded metadata hints for schedules; names never establish file contents."""

import re


def schedule_candidates(resources, modules):
    labels = {}
    for module in modules:
        for item in module.get("items", []):
            if item.get("material_ref"):
                labels.setdefault(item["material_ref"], []).extend(
                    [module["title"], item.get("title", "")]
                )
    candidates = []
    for resource in resources:
        names = [resource["title"], resource.get("filename") or "", *labels.get(resource["id"], [])]
        tokens = set(re.findall(r"[a-z]+", " ".join(names).casefold()))
        hints = tokens & {"schedule", "calendar", "syllabus", "timetable"}
        if not hints:
            continue
        priority = 0 if hints & {"schedule", "timetable"} else 1 if "calendar" in hints else 2
        pdf = resource.get("content_type") == "application/pdf" or any(
            n.lower().endswith(".pdf") for n in names[:2]
        )
        candidates.append(
            {
                "material_id": resource["id"],
                "title": resource["title"],
                "source_version": resource.get("source_version"),
                "discovery_basis": sorted(hints),
                "priority": priority,
                "format_priority": 0 if pdf else 1,
            }
        )
    return sorted(
        candidates,
        key=lambda c: (
            c["priority"],
            c["format_priority"],
            c["title"].casefold(),
            c["material_id"],
        ),
    )


def discovery_outcome(discovery, obligations):
    reviewed = [
        d for d in discovery["documents"] if d["state"] in {"reviewed", "partially_reviewed"}
    ]
    reviewed_ids = {d["material_id"] for d in reviewed}
    matching = sum(o["evidence"]["source_id"] in reviewed_ids for o in obligations)
    if not discovery["candidate_count"]:
        state = (
            "no_schedule_discovered"
            if discovery["mode"] == "automatic"
            else "no_materials_selected"
        )
    elif not reviewed:
        state = "schedule_not_reviewed"
    elif matching:
        state = "schedule_reviewed_with_candidates"
    elif any(d["state"] == "reviewed" for d in reviewed):
        state = "schedule_reviewed_no_matching_obligations"
    else:
        state = "schedule_partially_reviewed_no_matching_obligations"
    return {
        **discovery,
        "state": state,
        "matching_obligation_candidates": matching,
        "candidate_names_prove_schedule_content": False,
    }

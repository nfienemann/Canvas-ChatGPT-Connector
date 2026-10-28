"""Keep due-date history separate from evidence of an outstanding submission."""


def workload_status(item, now, zone):
    due = item.effective_due
    past_due = (
        due.timestamp < now
        if due.timestamp
        else due.local_date < now.astimezone(zone).date()
        if due.local_date
        else None
    )
    status = item.submission_state
    if item.assessment_state in {"graded", "excused"}:
        status = item.assessment_state
    requirement = set(item.submission_requirement.split(", "))
    online = bool(
        requirement
        & {
            "online_upload",
            "online_text_entry",
            "online_url",
            "media_recording",
            "online_quiz",
            "discussion_topic",
            "external_tool",
        }
    )
    if item.assessment_state == "excused":
        action, basis = (
            "none_indicated",
            "Canvas marks this work excused; this does not assert completion.",
        )
    elif item.revision_state == "requested":
        action, basis = "review_revision", "An explicit revision request requires review."
    elif item.submission_state in {"submitted", "resubmitted"}:
        action, basis = (
            "none_indicated",
            "Canvas records a submission; a past deadline alone does not require another submission.",
        )
    elif item.assessment_state == "graded":
        action, basis = (
            "unknown",
            "A grade alone does not establish completion or a submission requirement.",
        )
    elif item.submission_state == "not_submitted" and online:
        action, basis = (
            "submit",
            "Canvas explicitly reports unsubmitted work with an online submission requirement; offline completion is unknown.",
        )
    else:
        action, basis = (
            "unknown",
            "Offline completion, no-submission work, or uncertain submission evidence requires clarification.",
        )
    return {
        "due_date_relationship": "undated"
        if past_due is None
        else "past_due"
        if past_due
        else "not_yet_due",
        "work_status": status,
        "outstanding_action": action,
        "outstanding_action_basis": basis,
    }


def workload_section(status, undated=False):
    if undated:
        return "undated"
    if status["work_status"] in {"submitted", "resubmitted", "graded", "excused"}:
        return status["work_status"]
    if status["due_date_relationship"] == "past_due":
        return "overdue" if status["outstanding_action"] == "submit" else "past_due_unknown"
    return "upcoming"

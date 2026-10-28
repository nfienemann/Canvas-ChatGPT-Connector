"""Completion evidence is independent of current access and planning time."""


def completion_reason(item):
    if item.assessment_state == "excused":
        return "excused"
    if item.assessment_state == "graded" and item.revision_state in {"none_known", "unknown"}:
        return "graded_no_revision_indicated"
    if (
        item.submission_state == "not_applicable"
        and item.personal_progress == "student_marked_done"
    ):
        return "student_marked_done"
    if item.submission_state in {"submitted", "resubmitted"} and item.revision_state in {
        "none_known",
        "unknown",
    }:
        return "submitted_no_revision_indicated"
    return None

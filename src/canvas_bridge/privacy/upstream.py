"""Positive Canvas endpoint schemas at the first trusted processing boundary.

Unknown fields never reach normalizers/caches. Authentication identifiers exist
only in the few internal self-record schemas that need to verify identity.
"""

from canvas_bridge.policy import Endpoint
from canvas_bridge.privacy.identity import IdentityClass, PrivacyIdentity
from canvas_bridge.privacy_text import inspect_text


def fields(names):
    return dict.fromkeys(names.split(), None)


GRADES = fields("current_score final_score current_grade final_grade current_points final_points")
SELF = fields(
    "override_score override_grade current_period_override_score current_period_override_grade user_id course_id type enrollment_state role role_id current_grading_period_id totals_for_all_grading_periods current_period_computed_current_score current_period_computed_final_score current_period_computed_current_grade current_period_computed_final_grade"
) | {"grades": GRADES}
SUBMISSION = fields(
    "user_id assignment_id workflow_state submitted_at posted_at attempt excused missing late score grade assignment_visible cached_due_date seconds_late late_policy_status points_deducted"
)
RATING = fields("id description long_description points")
RUBRIC = fields("id description long_description points criterion_use_range") | {
    "ratings": [RATING]
}
ASSIGNMENT = fields(
    "id course_id name description due_at unlock_at lock_at updated_at created_at published locked_for_user hidden_to_user points_possible quiz_id assignment_group_id grading_type omit_from_final_grade html_url position allowed_attempts has_submitted_submissions"
) | {
    "checkpoints": [fields("tag due_at unlock_at lock_at")],
    "has_sub_assignments": None,
    "submission_types": [None],
    "allowed_extensions": [None],
    "submission": SUBMISSION,
    "discussion_topic": fields("id"),
    "rubric": [RUBRIC],
}
COURSE = fields(
    "id name course_code workflow_state time_zone syllabus_body apply_assignment_group_weights hide_final_grades has_grading_periods grading_standard_id"
) | {
    "enrollments": [SELF],
    "grading_periods": [fields("id title start_date end_date close_date weight is_closed")],
}
FILE = fields(
    "id display_name filename content-type size updated_at created_at modified_at locked_for_user hidden_for_user locked hidden url uuid lock_at unlock_at mime_class"
)
PAGE = fields(
    "page_id title url body updated_at created_at published locked_for_user front_page html_url"
)
TOPIC = (
    fields(
        "id course_id context_code locked subscription_hold due_at unlock_at lock_at title message html_url posted_at updated_at delayed_post_at published locked_for_user is_announcement assignment_id discussion_type"
    )
    | fields(
        "require_initial_post user_can_see_posts group_id group_category_id root_topic_id anonymous_state discussion_subentry_count reply_to_entry_required_count is_checkpointed"
    )
    | {
        "assignment": ASSIGNMENT,
        "group_topic_children": [fields("id group_id")],
        "attachments": [fields("id filename display_name content-type url")],
    }
)
SCHEMAS = {
    Endpoint.PROFILE: fields("id time_zone"),
    Endpoint.COURSES: COURSE,
    Endpoint.COURSE: COURSE,
    Endpoint.ASSIGNMENTS: ASSIGNMENT,
    Endpoint.ASSIGNMENT: ASSIGNMENT,
    Endpoint.ASSIGNMENT_GROUPS: fields("id name position group_weight")
    | {"rules": fields("drop_lowest drop_highest") | {"never_drop": [None]}},
    Endpoint.SUBMISSION: SUBMISSION,
    Endpoint.ENROLLMENTS: SELF,
    Endpoint.MODULES: fields(
        "id name position state published unlock_at require_sequential_progress items_count completed_at"
    )
    | {"prerequisite_module_ids": [None]},
    Endpoint.MODULE_ITEMS: fields(
        "id title type position content_id page_url published locked_for_user external_url html_url indent"
    )
    | {"completion_requirement": fields("type completed min_score")},
    Endpoint.PAGES: PAGE,
    Endpoint.PAGE: PAGE,
    Endpoint.ANNOUNCEMENTS: TOPIC,
    Endpoint.DISCUSSIONS: TOPIC,
    Endpoint.DISCUSSION: TOPIC,
    # Thread bodies require the specialized structural/self-only projector in
    # CanvasClient.discussion_page. Generic one/collection reads disclose nothing.
    Endpoint.DISCUSSION_VIEW: {},
    Endpoint.DISCUSSION_ENTRIES: {},
    Endpoint.DISCUSSION_REPLIES: {},
    Endpoint.DISCUSSION_DATES: fields(
        "id due_at reply_to_topic_due_at required_replies_due_at only_visible_to_overrides"
    )
    | {"checkpoints": [fields("tag due_at")]},
    Endpoint.QUIZZES: fields(
        "id course_id title description html_url due_at unlock_at lock_at published locked_for_user quiz_type assignment_id points_possible time_limit allowed_attempts updated_at"
    ),
    Endpoint.CALENDAR_EVENTS: fields(
        "id course_id effective_context_code hidden title description start_at end_at all_day all_day_date context_code html_url workflow_state location_name location_address updated_at assignment_id"
    )
    | {"assignment": ASSIGNMENT},
    Endpoint.FILE: FILE,
    Endpoint.FILES: FILE,
}
# Signed file URLs are transport inputs, never model output. Altering them here
# would break authentication. They remain bounded and origin-checked by FileDownloader.
TRANSPORT_FIELDS = {"url", "html_url", "external_url"}
SELF_SCHEMAS = (SELF, SUBMISSION)


def minimize_upstream(endpoint, payload, identity=None):
    identity = identity or PrivacyIdentity()
    if endpoint == Endpoint.CALENDAR_EVENTS and any(
        payload.get(k) for k in ("user", "group", "appointment_group_id")
    ):
        # Retain the exclusion semantics without retaining a participant record.
        return {"id": payload.get("id"), "workflow_state": "privacy_withheld"}
    schema = SCHEMAS.get(endpoint)
    if schema is None:
        return {}
    aliases = []
    nodes = 0

    def find_aliases(value, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 20 or nodes > 100_000 or len(aliases) > 256:
            from canvas_bridge.domain import DomainError

            raise DomainError(
                "permission_denied",
                "Content privacy inspection was incomplete.",
                reason_code="CONTENT_WITHHELD_PRIVACY_UNCERTAINTY",
            )
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {
                    "author",
                    "user",
                    "student",
                    "participants",
                    "last_edited_by",
                    "instructor",
                }:
                    people = item if isinstance(item, list) else [item]
                    for person in people:
                        if isinstance(person, dict):
                            aliases.extend(
                                v
                                for k, v in person.items()
                                if k
                                in {
                                    "name",
                                    "display_name",
                                    "sortable_name",
                                    "short_name",
                                    "login_id",
                                }
                                and isinstance(v, str)
                            )
                find_aliases(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:10_000]:
                find_aliases(item, depth + 1)

    find_aliases(payload)

    def project(value, spec, key="", depth=0):
        if depth > 20:
            return None
        if isinstance(spec, dict):
            if spec is SUBMISSION and value is None:
                return None
            if not isinstance(value, dict):
                return [] if spec is SUBMISSION else {}
            if any(spec is s for s in SELF_SCHEMAS):
                if identity.classify(value.get("user_id")) != IdentityClass.FIRST_PARTY_VERIFIED:
                    return {"user_id": None} if spec is SUBMISSION and value else {}
            return {k: project(v, spec[k], k, depth + 1) for k, v in value.items() if k in spec}
        if isinstance(spec, list):
            if not isinstance(value, list):
                return []
            return [project(v, spec[0], key, depth + 1) for v in value[:10_000]]
        if isinstance(value, (dict, list)):
            return False  # Preserve invalid-vs-absent semantics without retaining its payload.
        if isinstance(value, str):
            return (
                value[:250_000]
                if key in TRANSPORT_FIELDS
                else inspect_text(value, aliases[:256])[0]
            )
        return value if value is None or type(value) in {bool, int, float} else None

    result = project(payload, schema)
    if endpoint == Endpoint.DISCUSSION_DATES:
        # Date details may describe everyone/sections, not the requesting student.
        # Never retain override student IDs or guess section/group applicability.
        result["overrides_uncertain"] = (
            bool(payload.get("overrides")) or payload.get("only_visible_to_overrides") is True
        )
    return result

"""Fresh, bounded discussion evidence for the authenticated student only.

No thread cache, raw peer persistence, group inference, or Canvas mutations.
An empty partial scan is never evidence of nonparticipation.
"""

import asyncio
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field

from canvas_bridge.domain import DomainError, Model, Result, Source, utcnow
from canvas_bridge.evidence import fingerprint
from canvas_bridge.normalize import canonical_id, fact_date, plain_text
from canvas_bridge.policy import Endpoint, source_id

State = Literal[
    "verified_present",
    "verified_absent",
    "partial",
    "access_restricted",
    "identity_ambiguous",
    "unavailable",
]
NOTICE = "Observed activity is not a grade, rubric assessment, or instructor-accepted completion. A fresh request cannot eliminate Canvas visibility delays."


class DiscussionCoverage(Model):
    complete: bool = False
    partial_reasons: list[str] = Field(default_factory=list)
    pages_fetched: int = 0
    entries_examined: int = 0
    pagination_exhausted: bool = False
    source_strategy: str = "metadata_only"
    fetched_at: datetime = Field(default_factory=lambda: utcnow())
    cache_age_seconds: int = 0
    identity_verified: bool = False
    group_scope_verified: bool | None = None


class DiscussionTopic(Model):
    course_id: str
    topic_id: str
    group_id: str | None = None
    group_scope: str = "course"
    title: str = "Discussion"
    prompt_text: str = ""
    prompt_truncated: bool = False
    canvas_url: str
    assignment_id: str | None = None
    discussion_type: str = "unknown"
    require_initial_post: bool | None = None
    user_can_see_posts: bool | None = None
    published: bool | None = None
    locked_for_user: bool | None = None
    archived: bool | None = None
    is_checkpointed: bool | None = None
    initial_due_at: datetime | None = None
    replies_due_at: datetime | None = None
    required_reply_count: int | None = None
    deadline_sources: list[str] = Field(default_factory=list)
    deadline_warnings: list[str] = Field(default_factory=list)
    visibility_restrictions: list[str] = Field(default_factory=list)
    attachments: list[dict] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: utcnow())
    coverage: DiscussionCoverage = Field(default_factory=DiscussionCoverage)


class StudentEntry(Model):
    entry_id: str
    topic_id: str
    parent_entry_id: str | None
    kind: Literal["top_level_post", "reply"]
    author: Literal["self"] = "self"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    message_text: str = ""
    text_truncated: bool = False
    deleted: bool = False
    source_url: str
    source_endpoint: str
    verification_state: str = "verified_self"
    deadline_comparison: str = "deadline_unknown"


class Participation(Model):
    state: State
    participation_verified: bool = False
    top_level_posts: int = 0
    replies: int = 0
    initial_post_state: State
    additional_replies_state: State
    entries: list[StudentEntry] = Field(default_factory=list)
    coverage: DiscussionCoverage
    fetched_at: datetime
    confidence: str
    count_basis: str = "verified_non_deleted_entries; lower bounds when coverage is partial"
    remaining_replies_by_count: int | None = None
    completion_state: str = "not_assessed"
    limitations: list[str] = Field(default_factory=lambda: [NOTICE])


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        return source_id(value)
    except DomainError:
        return None


def boolean(raw, key):
    return raw.get(key) if type(raw.get(key)) is bool else None


def timestamp(raw, key):
    return fact_date(raw, key).timestamp


def normalize_topic(raw, course_id, canvas_course, origin, *, text_limit=16000, prompt=True):
    tid = numeric(raw.get("id"))
    if not tid or ("course_id" in raw and str(raw["course_id"]) != canvas_course):
        raise DomainError(
            "permission_denied",
            "Discussion ownership could not be verified.",
            reason_code="DISCUSSION_CONTEXT_MISMATCH",
        )
    if raw.get("context_code") not in {None, "course_" + canvas_course}:
        raise DomainError(
            "permission_denied",
            "Discussion context could not be verified.",
            reason_code="DISCUSSION_CONTEXT_MISMATCH",
        )
    url = f"{origin}/courses/{canvas_course}/discussion_topics/{tid}"
    # A mismatched URL is evidence of a different context, never a redirect target.
    if raw.get("html_url") and raw["html_url"].rstrip("/") != url:
        raise DomainError(
            "permission_denied",
            "Discussion source context differs.",
            reason_code="DISCUSSION_CONTEXT_MISMATCH",
        )
    group = any(
        raw.get(k)
        for k in ("group_id", "group_category_id", "root_topic_id", "group_topic_children")
    ) or raw.get("subscription_hold") in {"not_in_group", "not_in_group_set"}
    restrictions = []
    if group:
        restrictions.append("group_access_uncertain")
    if raw.get("published") is not True or raw.get("locked_for_user") is not False:
        restrictions.append("topic_visibility_unverified")
    if raw.get("is_announcement") is True:
        restrictions.append("announcement_excluded")
    for key in ("unlock_at", "delayed_post_at"):
        if timestamp(raw, key) and timestamp(raw, key) > utcnow():
            restrictions.append("not_yet_available")
    if raw.get("require_initial_post") is True and raw.get("user_can_see_posts") is not True:
        restrictions.append("require_initial_post")
    elif raw.get("user_can_see_posts") is not True:
        restrictions.append("thread_visibility_unverified")
    if raw.get("anonymous_state") not in {None, "off"}:
        restrictions.append("anonymous_authorship")
    prompt_allowed = not set(restrictions) & {
        "group_access_uncertain",
        "topic_visibility_unverified",
        "announcement_excluded",
        "not_yet_available",
    }
    message = raw.get("message") if prompt and prompt_allowed else ""
    text = plain_text(message, text_limit + 1) if isinstance(message, str) else ""
    topic = DiscussionTopic(
        course_id=course_id,
        topic_id=tid,
        canvas_url=url,
        title=plain_text(str(raw.get("title") or "Discussion"), 500),
        group_scope="unverified_group" if group else "course",
        prompt_text=text[:text_limit],
        prompt_truncated=len(text) > text_limit
        or isinstance(message, str)
        and len(message) > (text_limit + 1) * 4,
        assignment_id=numeric(raw.get("assignment_id")),
        discussion_type=raw.get("discussion_type")
        if raw.get("discussion_type") in {"threaded", "side_comment", "not_threaded"}
        else "unknown",
        require_initial_post=boolean(raw, "require_initial_post"),
        user_can_see_posts=boolean(raw, "user_can_see_posts"),
        published=boolean(raw, "published"),
        locked_for_user=boolean(raw, "locked_for_user"),
        archived=boolean(raw, "locked"),
        visibility_restrictions=sorted(set(restrictions)),
        is_checkpointed=boolean(raw, "is_checkpointed"),
        required_reply_count=raw.get("reply_to_entry_required_count")
        if type(raw.get("reply_to_entry_required_count")) is int
        and 0 <= raw["reply_to_entry_required_count"] <= 10000
        else None,
        coverage=DiscussionCoverage(
            complete=True,
            pagination_exhausted=True,
            pages_fetched=1,
            group_scope_verified=False if group else None,
        ),
    )
    assignment = raw.get("assignment")
    if (
        isinstance(assignment, dict)
        and numeric(assignment.get("id")) == topic.assignment_id
        and topic.assignment_id
    ):
        apply_assignment_dates(topic, assignment, canvas_course)
    if prompt_allowed and prompt:
        for item in (raw.get("attachments") or [])[:20]:
            parsed = urlsplit(str(item.get("url", "")))
            parts = parsed.path.strip("/").split("/")
            fid = (
                numeric(parts[3])
                if len(parts) in {4, 5} and parts[:3] == ["courses", canvas_course, "files"]
                else None
            )
            if (
                fid
                and parsed.scheme == "https"
                and parsed.netloc == urlsplit(origin).netloc
                and not parsed.fragment
                and not parsed.query
                and (len(parts) == 4 or parts[-1] == "download")
            ):
                topic.attachments.append(
                    {
                        "file_id": fid,
                        "filename": plain_text(
                            str(item.get("filename") or "Canvas attachment"), 200
                        ),
                        "source_url": f"{origin}/courses/{canvas_course}/files/{fid}",
                        "access_state": "reference_only; use authorized course file tools",
                    }
                )
    return topic


def apply_assignment_dates(topic, assignment, canvas_course):
    if numeric(assignment.get("id")) != topic.assignment_id or (
        "course_id" in assignment and str(assignment["course_id"]) != canvas_course
    ):
        topic.deadline_warnings.append("assignment_identity_mismatch")
        return
    if assignment.get("locked_for_user") is True or assignment.get("published") is False:
        topic.deadline_warnings.append("assignment_access_restricted")
        return
    checkpoints = assignment.get("checkpoints", [])
    if isinstance(checkpoints, list) and checkpoints:
        for tag, field in (
            ("reply_to_topic", "initial_due_at"),
            ("reply_to_entry", "replies_due_at"),
        ):
            candidates = [
                timestamp(c, "due_at")
                for c in checkpoints
                if isinstance(c, dict) and c.get("tag") == tag
            ]
            if len(candidates) == 1:
                setattr(topic, field, candidates[0])
            elif candidates:
                setattr(topic, field, None)
                topic.deadline_warnings.append("conflicting_checkpoint_dates")
    elif assignment.get("has_sub_assignments") is not True and topic.is_checkpointed is not True:
        topic.initial_due_at = timestamp(assignment, "due_at")
    topic.deadline_sources.append("assignment_effective_dates")


async def hydrate_dates(client, topic, canvas_course):
    ids = {"course": canvas_course, "topic": topic.topic_id}
    details = None
    try:
        details = await client.one(Endpoint.DISCUSSION_DATES, **ids)
    except DomainError as exc:
        if exc.upstream_http_status is None and exc.status != "retry_later":
            raise
        topic.deadline_warnings.append("date_details_unavailable")
    if topic.assignment_id:
        try:
            assignment = await client.one(
                Endpoint.ASSIGNMENT,
                course=canvas_course,
                assignment=topic.assignment_id,
                discussion_checkpoints=True,
            )
            apply_assignment_dates(topic, assignment, canvas_course)
        except DomainError as exc:
            if (
                exc.reason_code not in {"MISSING_RESOURCE_CAPABILITY"}
                and exc.upstream_http_status is None
                and exc.status != "retry_later"
            ):
                raise
            topic.deadline_warnings.append("assignment_dates_unavailable")
    if details:
        if numeric(details.get("id")) != topic.topic_id or details.get("overrides_uncertain"):
            topic.deadline_warnings.append("date_details_not_student_effective")
        else:
            for key, field in (
                ("reply_to_topic_due_at", "initial_due_at"),
                ("required_replies_due_at", "replies_due_at"),
            ):
                value, previous = timestamp(details, key), getattr(topic, field)
                if previous and value and previous != value:
                    topic.deadline_warnings.append("conflicting_discussion_assignment_deadlines")
                    # An unresolved conflict cannot support an on-time assertion.
                    setattr(topic, field, None)
                elif not previous and "assignment_effective_dates" not in topic.deadline_sources:
                    setattr(topic, field, value)
            topic.deadline_sources.append("discussion_date_details")
    topic.deadline_sources = sorted(set(topic.deadline_sources))


def reason_for(error):
    if error.upstream_http_status == 429:
        return "rate_limited"
    if error.upstream_http_status in {401, 403, 404}:
        return "access_restricted"
    if error.reason_code == "UPSTREAM_UNAVAILABLE" or error.status == "retry_later":
        return "request_unavailable"
    return "unsupported_response"


class ThreadScan:
    def __init__(self, client, topic, course, *, expected_count=None, budget_seconds=None):
        self.client, self.topic, self.course = client, topic, course
        self.records, self.conflicts, self.reasons = {}, set(), set()
        self.fallback_ids = set()
        self.coverage = DiscussionCoverage(
            identity_verified=bool(client.privacy_identity.canvas_user),
            group_scope_verified=topic.coverage.group_scope_verified,
        )
        self.requests = 0
        self.expected_count = (
            expected_count if type(expected_count) is int and expected_count >= 0 else None
        )
        self.budget_seconds = (
            min(client.settings.discussion_budget_seconds, budget_seconds)
            if budget_seconds is not None
            else client.settings.discussion_budget_seconds
        )

    def merge(self, records, endpoint, request_path):
        for row in records:
            self.coverage.entries_examined += 1
            if self.coverage.entries_examined > self.client.settings.discussion_max_entries:
                self.reasons.add("entry_limit")
                return
            key = numeric(row.get("id"))
            if not key:
                self.reasons.add("unsupported_response")
                continue
            if endpoint != Endpoint.DISCUSSION_VIEW:
                self.fallback_ids.add(key)
            parent = row.get("parent_id")
            if (
                row.get("parent_unknown")
                or parent is not None
                and (not numeric(parent) or str(parent) == key)
            ):
                self.reasons.add("parent_relationship_unknown")
                self.conflicts.add(key)
            new = {
                **row,
                "id": key,
                "parent_id": numeric(parent),
                "source_endpoint": request_path,
            }
            old = self.records.get(key)
            if old:
                # Delivery shape (recent replies, endpoint) is not a content version.
                fields = (
                    "identity_state",
                    "parent_id",
                    "parent_unknown",
                    "created_at",
                    "updated_at",
                    "message_text",
                    "deleted",
                    "message_available",
                )
                if any(old.get(k) != new.get(k) for k in fields):
                    before, after = timestamp(old, "updated_at"), timestamp(new, "updated_at")
                    stable = (
                        old.get("identity_state") == new.get("identity_state")
                        and old.get("created_at") == new.get("created_at")
                        and old.get("parent_id") == new.get("parent_id")
                    )
                    if stable and before and after and before != after:
                        if before > after:
                            continue
                    elif new.get("deleted") is True and before and after and after > before:
                        pass
                    else:
                        self.conflicts.add(key)
                        self.reasons.add("stale_thread_view")
            self.records[key] = new

    async def page(self, endpoint, cursor=None, **extra):
        if self.requests >= min(
            self.client.settings.discussion_max_pages, self.client.settings.max_pages
        ):
            self.reasons.add("pagination_limit")
            return None, None
        self.requests += 1
        data, next_link = await self.client.discussion_page(
            endpoint, cursor=cursor, course=self.course, topic=self.topic.topic_id, **extra
        )
        self.coverage.pages_fetched += 1
        self.reasons.update(data["reasons"])
        request_path = endpoint.value.format(course=self.course, topic=self.topic.topic_id, **extra)
        self.merge(data["records"], endpoint, request_path)
        self.merge(data["new_records"], endpoint, request_path)
        return data, next_link

    async def pages(self, endpoint, **extra):
        cursor, seen = None, set()
        while True:
            if cursor in seen:
                self.reasons.add("pagination_loop")
                return False
            seen.add(cursor)
            data, cursor = await self.page(endpoint, cursor, **extra)
            if data is None or "entry_limit" in self.reasons:
                return False
            if cursor is None:
                return True

    async def run(self):
        restrictions = set(self.topic.visibility_restrictions)
        if restrictions or not self.coverage.identity_verified:
            self.reasons.update(restrictions or {"identity_unverified"})
            return self.finish()
        self.coverage.source_strategy = "full_view"
        try:
            async with asyncio.timeout(self.budget_seconds):
                full = None
                try:
                    full, cursor = await self.page(Endpoint.DISCUSSION_VIEW)
                except DomainError as exc:
                    if exc.status in {"permission_denied", "reconnect_required", "source_changed"}:
                        raise
                    # A failed/unsupported full view may be replaced by a complete fallback.
                sufficient = (
                    full is not None
                    and full["reconciled"]
                    and cursor is None
                    and not self.reasons
                    and not any(r.get("has_more_replies") for r in self.records.values())
                )
                if sufficient:
                    self.coverage.pagination_exhausted = True
                else:
                    self.coverage.source_strategy = (
                        "combination" if self.records else "paginated_fallback"
                    )
                    view_ids = set(self.records)
                    recovered = await self.pages(Endpoint.DISCUSSION_ENTRIES)
                    checked = set()
                    while True:
                        pending = [
                            k
                            for k, r in self.records.items()
                            if r.get("has_more_replies") is True and k not in checked
                        ]
                        if not pending:
                            break
                        for key in pending:
                            checked.add(key)
                            if not await self.pages(Endpoint.DISCUSSION_REPLIES, entry=key):
                                self.reasons.add("missing_replies")
                                recovered = False
                        if "pagination_limit" in self.reasons or "entry_limit" in self.reasons:
                            break
                    self.coverage.pagination_exhausted = recovered
                    if recovered and view_ids - self.fallback_ids:
                        self.reasons.add("stale_thread_view")
                        self.conflicts.update(view_ids - self.fallback_ids)
        except TimeoutError:
            self.reasons.add("request_timeout")
        except DomainError as exc:
            if exc.upstream_http_status is None and exc.status in {
                "permission_denied",
                "reconnect_required",
                "source_changed",
            }:
                raise
            self.reasons.add(reason_for(exc))
            if exc.upstream_http_status in {401, 403, 404}:
                # Do not retain earlier content after permission loss.
                self.records.clear()
        return self.finish()

    def finish(self):
        entries = []
        if self.expected_count is not None and len(self.records) < self.expected_count:
            self.reasons.add("stale_thread_view")
        for key, row in self.records.items():
            if row.get("deleted") is True:
                continue
            if row.get("identity_state") == "unknown":
                self.reasons.add("anonymous_authorship")
            if not row.get("message_available"):
                self.reasons.add("deleted_entry_uncertainty")
            if (
                key in self.conflicts
                or row.get("identity_state") != "self"
                or not row.get("message_available")
            ):
                continue
            parent = row.get("parent_id")
            kind = "reply" if parent is not None else "top_level_post"
            created = timestamp(row, "created_at")
            due = self.topic.replies_due_at if parent is not None else self.topic.initial_due_at
            entries.append(
                StudentEntry(
                    entry_id=key,
                    topic_id=self.topic.topic_id,
                    parent_entry_id=parent,
                    kind=kind,
                    created_at=created,
                    updated_at=timestamp(row, "updated_at"),
                    message_text=row.get("message_text", ""),
                    text_truncated=row.get("text_truncated", False),
                    source_url=self.topic.canvas_url + "#entry-" + key,
                    source_endpoint=row["source_endpoint"],
                    deadline_comparison="timestamp_unknown"
                    if created is None
                    else "deadline_unknown"
                    if due is None
                    else "observed_on_time"
                    if created <= due
                    else "observed_late",
                )
            )
        self.coverage.partial_reasons = sorted(self.reasons)
        self.coverage.complete = (
            self.coverage.pagination_exhausted
            and self.coverage.identity_verified
            and not self.reasons
        )
        self.coverage.fetched_at = utcnow()
        top = sum(e.kind == "top_level_post" for e in entries)
        replies = len(entries) - top
        unknown: State = "partial"
        if self.reasons & {
            "access_restricted",
            "require_initial_post",
            "topic_visibility_unverified",
            "thread_visibility_unverified",
            "group_access_uncertain",
            "not_yet_available",
            "announcement_excluded",
        }:
            unknown = "access_restricted"
        elif self.reasons & {"anonymous_authorship", "identity_unverified"}:
            unknown = "identity_ambiguous"
        elif self.coverage.pages_fetched == 0 and self.reasons & {
            "request_unavailable",
            "request_timeout",
            "rate_limited",
            "unsupported_response",
        }:
            unknown = "unavailable"
        absent: State = "verified_absent" if self.coverage.complete else unknown
        return Participation(
            state=("verified_present" if entries else "verified_absent")
            if self.coverage.complete
            else unknown,
            participation_verified=bool(entries),
            top_level_posts=top,
            replies=replies,
            initial_post_state="verified_present" if top else absent,
            additional_replies_state="verified_present"
            if replies and self.coverage.complete
            else "partial"
            if replies
            else absent,
            entries=entries,
            coverage=self.coverage,
            fetched_at=self.coverage.fetched_at,
            confidence="complete_authorized_scan"
            if self.coverage.complete
            else "bounded_evidence_only",
            remaining_replies_by_count=max(0, self.topic.required_reply_count - replies)
            if self.coverage.complete and self.topic.required_reply_count is not None
            else None,
        )


def provenance(owner, ref, topic, data):
    return Source(
        id=canonical_id(owner, ref, "discussion", topic.course_id + ":" + topic.topic_id),
        url=topic.canvas_url,
        title=topic.title,
        retrieved_at=utcnow(),
        source_type="discussion_topics",
        course_id=topic.course_id,
        content_hash=fingerprint(data),
        extraction_status="self_only",
    )


async def discussion_request(
    bridge,
    owner,
    ref,
    course_id,
    topic_id,
    *,
    include_entries=False,
    entry_scope="self_only",
    limit=100,
    refresh=False,
    participation_only=False,
):
    if entry_scope not in {"self_only", "authorized_thread"} or not 1 <= limit <= 100:
        raise DomainError("needs_input", "Choose a supported discussion scope and limit.")
    if entry_scope == "authorized_thread":
        raise DomainError(
            "permission_denied",
            "Peer thread disclosure requires separate authorization and a reviewed disclosure implementation.",
            reason_code="THIRD_PARTY_DISCLOSURE_NOT_AUTHORIZED",
        )
    tid = source_id(topic_id)
    decision = bridge.authorize(owner, ref, course_id, "discussions", Endpoint.DISCUSSION).require()
    course = decision.course
    deadline = asyncio.get_running_loop().time() + bridge.settings.discussion_budget_seconds
    async with bridge.client(owner, ref, refresh_credentials=False, course_ref=course_id) as client:
        try:
            async with asyncio.timeout(max(0, deadline - asyncio.get_running_loop().time())):
                raw = await client.one(Endpoint.DISCUSSION, course=course.source_id, topic=tid)
        except TimeoutError as exc:
            raise DomainError(
                "retry_later",
                "Discussion metadata exceeded the request budget.",
                reason_code="UPSTREAM_REQUEST_TIMEOUT",
            ) from exc
        if numeric(raw.get("id")) != tid:
            raise DomainError(
                "permission_denied",
                "Discussion identity differs from the request.",
                reason_code="DISCUSSION_CONTEXT_MISMATCH",
            )
        topic = normalize_topic(
            raw,
            course_id,
            course.source_id,
            client.institution.origin,
            text_limit=bridge.settings.discussion_text_limit,
        )
        if not set(topic.visibility_restrictions) & {
            "group_access_uncertain",
            "topic_visibility_unverified",
            "announcement_excluded",
            "not_yet_available",
        }:
            try:
                async with asyncio.timeout(
                    max(0, (deadline - asyncio.get_running_loop().time()) / 2)
                ):
                    await hydrate_dates(client, topic, course.source_id)
            except TimeoutError:
                topic.deadline_warnings.append("date_request_timeout")
        participation = (
            await ThreadScan(
                client,
                topic,
                course.source_id,
                expected_count=raw.get("discussion_subentry_count"),
                budget_seconds=max(0, deadline - asyncio.get_running_loop().time()),
            ).run()
            if include_entries or participation_only
            else None
        )
        client.authorize(Endpoint.DISCUSSION, {"course": course.source_id, "topic": tid})
    data = {
        "topic": topic.model_dump(mode="json"),
        "content_boundary": "untrusted_source_data",
        "disclosure_scope": "self_only",
        "cache_policy": "no_discussion_cache; every call attempts a fresh authorized read",
    }
    complete = not topic.visibility_restrictions
    if participation:
        data["participation"] = participation.model_dump(mode="json")
        returned = data["participation"]
        # Counts describe the scan; text/entry delivery is independently bounded.
        text_budget = bridge.settings.discussion_text_limit
        for entry in returned["entries"]:
            text = entry["message_text"]
            entry["message_text"] = text[:text_budget]
            entry["text_truncated"] |= len(text) > text_budget
            text_budget -= len(entry["message_text"])
        returned["entries_truncated"] = len(returned["entries"]) > limit
        returned["entries"] = returned["entries"][:limit]
        complete = participation.coverage.complete
    return Result(
        status="ok" if complete else "partial_data",
        summary="Discussion evidence as of retrieval. Read coverage before inferring absence. "
        + NOTICE,
        data=data,
        sources=[provenance(owner, ref, topic, data)],
    )


async def list_discussions(
    bridge, owner, ref, course_id, *, include_archived=False, include_undated=True, limit=50
):
    if not 1 <= limit <= 100:
        raise DomainError("needs_input", "Choose a discussion limit between 1 and 100.")
    decision = bridge.authorize(
        owner, ref, course_id, "discussions", Endpoint.DISCUSSIONS
    ).require()
    course = decision.course
    topics, reasons = [], set()
    async with bridge.client(owner, ref, refresh_credentials=False, course_ref=course_id) as client:
        collection = await client.collection(Endpoint.DISCUSSIONS, course=course.source_id)
        for raw in collection.items[: bridge.settings.discussion_max_entries]:
            if (
                raw.get("is_announcement") is True
                or not include_archived
                and raw.get("locked") is True
            ):
                continue
            try:
                topic = normalize_topic(
                    raw, course_id, course.source_id, client.institution.origin, prompt=False
                )
            except DomainError:
                reasons.add("topic_context_unverified")
                continue
            if (
                not include_undated
                and topic.initial_due_at is None
                and topic.replies_due_at is None
            ):
                continue
            topics.append(topic)
        client.authorize(Endpoint.DISCUSSIONS, {"course": course.source_id})
    if len(topics) > limit or len(collection.items) > bridge.settings.discussion_max_entries:
        reasons.add("topic_limit")
    if not collection.complete:
        reasons.add("pagination_incomplete")
    topics = topics[:limit]
    coverage = DiscussionCoverage(
        complete=collection.complete and not reasons,
        partial_reasons=sorted(reasons),
        pages_fetched=collection.pages,
        pagination_exhausted=collection.complete,
        identity_verified=True,
    )
    data = {
        "course_id": course_id,
        "topics": [t.model_dump(mode="json") for t in topics],
        "coverage": coverage.model_dump(mode="json"),
        "limitations": [
            "List reads metadata only. Read a topic for date details and participation; missing dates remain unknown."
        ],
    }
    return Result(
        status="ok" if coverage.complete else "partial_data",
        summary="Accessible discussion metadata; no thread entries were requested.",
        data=data,
        sources=[provenance(owner, ref, t, t.model_dump(mode="json")) for t in topics],
    )

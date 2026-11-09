"""Service adapters for independent-source usefulness workflows."""

import base64
import re

from canvas_bridge.academic.independent_models import IndependentAcademicInput
from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import RecipientPolicy, SourceContext
from canvas_bridge.evidence import fingerprint
from canvas_bridge.independent_intelligence import require, require_use
from canvas_bridge.storage import IndependentResource
from canvas_bridge.usefulness.engine import PRACTICE, check_control, obligations, transitions
from canvas_bridge.usefulness.imports import Imports, compile_review
from canvas_bridge.usefulness.models import Attempt
from canvas_bridge.usefulness.records import Records
from canvas_bridge.usefulness.search import cursor_offset, seal_cursor

TOOL = "run_local_study_workflow"


def scoped_work_id(document_id, key):
    return "work_" + fingerprint([document_id, key])[:48]


class Usefulness:
    def __init__(self, bridge):
        self.bridge = bridge
        self.records = Records(bridge)
        self.imports = Imports(bridge)

    def enabled(self):
        if not self.bridge.settings.usefulness_features_enabled:
            raise DomainError(
                "unsupported_feature",
                "Independent review workflows are disabled in this deployment.",
            )

    def save_review(
        self,
        owner,
        document_id,
        expected_hash,
        decisions,
        *,
        expected_revision=0,
        timezone=None,
        key,
        groups=None,
        validate_session=lambda: None,
    ):
        self.enabled()
        row = self.bridge.independent.require(owner, document_id)
        if row.version_hash != expected_hash:
            raise DomainError(
                "source_changed", "The document changed. Review its current passages."
            )
        review = compile_review(row, decisions, timezone=timezone)
        if groups is None:
            groups = row.content.get("reviewed_dataset", {}).get("requirement_groups", [])
        if groups is not None:
            review["dataset"] = IndependentAcademicInput.model_validate(
                review["dataset"] | {"requirement_groups": groups}
            ).model_dump(mode="json")
        prior = row.content.get("review")
        if not prior:
            history = row.content.get("version_history", [])
            prior = history[-1].get("review") if history else None

        def publish(session, record):
            current = session.get(IndependentResource, document_id)
            if not current or current.owner != owner or current.version_hash != expected_hash:
                raise DomainError(
                    "source_changed", "The document changed before the review was saved."
                )
            current_review = current.content.get("review")
            if not current_review:
                history = current.content.get("version_history", [])
                current_review = history[-1].get("review") if history else None
            prior_revision = (current_review or {}).get("revision", 0)
            if (
                current_review
                and current.content.get("packet")
                and not current.content.get("review")
            ):
                saved = self.records.repo._load(session, owner)[1].records.get(
                    current_review.get("record_id")
                )
                if saved and saved.state == "stale":
                    prior_revision = saved.revision
            if prior_revision != expected_revision:
                raise DomainError(
                    "source_changed", "Another review was saved; refresh the reviewed selections."
                )
            current.content = current.content | {
                "review": {
                    "record_id": record.id,
                    "revision": record.revision,
                    "source_hash": expected_hash,
                    "observed_at": record.updated_at.isoformat(),
                },
                "reviewed_dataset": review["dataset"],
            }

        return self.records.save(
            owner,
            row.content.get("course", "independent"),
            "import_review",
            review,
            record_id=prior["record_id"] if prior else None,
            expected_revision=expected_revision,
            idempotency_key=key,
            share=row.provenance.get("share_text", False),
            sources=[self.records.document_tag(owner, row)],
            validate_session=validate_session,
            publish=publish,
            identity_hint=document_id,
        )

    def save_attempt(
        self,
        owner,
        course,
        value,
        *,
        key,
        share,
        record_id=None,
        expected_revision=0,
        document_ids=(),
        validate_session=lambda: None,
    ):
        self.enabled()
        attempt = Attempt.model_validate(value)
        settings = self.records.rows(owner, course, "collection")
        if settings and not settings[-1].data["value"]["enabled"]:
            raise DomainError(
                "needs_input", "Study history collection is disabled for this course."
            )
        goal = self.records.repo.read(owner, attempt.goal_id)
        if goal.scope.course != course or goal.data.get("subtype") != "goal":
            raise DomainError("permission_denied", "Select a goal in this course.")
        data = attempt.model_dump(mode="json")
        data["evaluation"] = (
            check_control(attempt.response)
            if attempt.check == "control_purpose"
            else {
                "evaluation_method": "provisional_host_interpretation"
                if attempt.evidence_kind == "host_interpretation"
                else "student_report_or_unchecked_response",
                "mastery_established": False,
            }
        )
        sources = list(goal.sources)
        if record_id:
            previous = self.records.repo.read(owner, record_id)
            # A correction cannot erase its source lineage by omitting a checkbox.
            sources.extend(previous.sources)
        for ident in document_ids:
            row = self.bridge.independent.require(owner, ident)
            if row.content.get("course", "independent") != course:
                raise DomainError(
                    "permission_denied", "The selected source is unavailable in this course."
                )
            sources.append(self.records.document_tag(owner, row))

        def enforce_collection(session, record):
            state = self.records.repo._load(session, owner)[1]
            if any(
                r.scope.course == course
                and r.data.get("schema") == "usefulness-1"
                and r.data.get("subtype") == "collection"
                and not r.data["value"]["enabled"]
                for r in state.records.values()
            ):
                raise DomainError(
                    "needs_input", "Study history collection is disabled for this course."
                )

        return self.records.save(
            owner,
            course,
            "attempt",
            data,
            record_id=record_id,
            expected_revision=expected_revision,
            idempotency_key=key,
            share=share,
            sources=tuple({s.key: s for s in sources}.values()),
            depends_on=(goal.id,),
            validate_session=validate_session,
            publish=enforce_collection,
        )

    def permits_record(self, source, transfer):
        record = self.records.repo.read(transfer.principal, source.source_id)
        profile = self.bridge.independent.profile()
        if (
            record.data.get("schema") != "usefulness-1"
            or not record.data.get("share")
            or not profile
            or not record.data.get("recipient_policy")
            or RecipientPolicy.model_validate(record.data["recipient_policy"]) != profile
            or source.version != fingerprint(record.model_dump(mode="json"))
        ):
            return False
        recipient = transfer.recipient
        if self.bridge.settings.profile != "synthetic" and (
            recipient.recipient,
            recipient.issuer,
            recipient.client_id,
            recipient.environment,
            recipient.workspace,
        ) != (
            profile.recipient,
            profile.issuer,
            profile.client_id,
            profile.environment,
            profile.workspace,
        ):
            return False
        if not (
            recipient.recipient == profile.recipient
            and transfer.purpose in profile.purposes
            and transfer.channel in profile.channels
            and transfer.amount <= profile.max_output_bytes
            and CC.FIRST_PARTY_EDUCATIONAL_RECORD in profile.classifications
        ):
            return False
        for tag in record.sources:
            if tag.origin == "local_document":
                context = SourceContext(
                    "__independent__",
                    transfer.principal,
                    tag.id,
                    tag.version,
                    "local_document",
                    CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                )
                if not self.bridge.independent.permits(context, transfer):
                    return False
        return True

    def resolve_sources(self, owner, result):
        resolved = []
        for source in result.sources:
            if source.source_type == "local_study_record":
                record = self.records.repo.read(owner, source.id)
                if fingerprint(record.model_dump(mode="json")) != source.content_hash:
                    raise DomainError("source_changed", "Saved study state changed; refresh it.")
                resolved.append(
                    SourceContext(
                        "__independent__",
                        owner,
                        source.id,
                        source.content_hash,
                        "local_study_record",
                        CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                    )
                )
            else:
                row = self.bridge.independent.require(owner, source.id)
                if row.version_hash != source.content_hash:
                    raise DomainError("source_changed", "A selected document changed; refresh it.")
                resolved.extend(
                    self.bridge.independent.sources(owner, {"document_id": source.id}, result)
                )
        return tuple(resolved) or (
            SourceContext(
                "__public__", owner, "empty-local-study", "", "safe_status", CC.PUBLIC_OR_APPROVED
            ),
        )

    def release(self, owner, result, *, operation=None):
        # Include inherited document lineage in the ordinary integrity guard as
        # well as the egress check. Saving history cannot bypass source policy.
        from canvas_bridge.academic.independent_models import DocumentSelection

        citations = {s.id: s for s in result.sources}
        for citation in list(citations.values()):
            if citation.source_type != "local_study_record":
                continue
            record = self.records.repo.read(owner, citation.id)
            for tag in record.sources:
                if tag.origin == "local_document":
                    row = require(
                        self.bridge,
                        owner,
                        DocumentSelection(document_id=tag.id, expected_hash=tag.version),
                    )
                    if row.content.get("course", "independent") != tag.scope.course:
                        raise DomainError(
                            "source_changed", "The source course changed; review dependent state."
                        )
                    citations[row.id] = self.bridge.independent.evidence(row)
        result.sources = list(citations.values())
        if len(result.model_dump_json().encode()) > 100_000:
            raise DomainError(
                "needs_input",
                "Narrow the selected sources or saved records to fit the response budget.",
            )
        arguments = {"request": {"operation": operation}} if operation else {}
        return self.bridge.egress.release(result, owner, arguments, tool_name=TOOL)

    def shared_records(self, owner, course, subtype, *, operation=None):
        result = []
        for record in self.records.rows(owner, course, subtype):
            try:
                self.release(
                    owner,
                    Result(
                        summary="Selected local record.", sources=[self.records.citation(record)]
                    ),
                    operation=operation,
                )
            except DomainError:
                continue
            result.append(record)
        return result

    async def documents(self, owner, request):
        from canvas_bridge.integrity.surfaces import before_tool

        rows, unavailable = [], False
        for selection in request.documents:
            try:
                row = require(self.bridge, owner, selection, check_version=False)
                require_use(
                    self.bridge,
                    row,
                    "planning" if request.operation in {"obligations", "changes"} else "assessment",
                )
                if row.content.get("course", "independent") != request.course:
                    raise DomainError("permission_denied", "Source unavailable in this course.")
                await before_tool(
                    self.bridge, owner, "read_local_document", {"document_id": row.id}
                )
                self.release(
                    owner,
                    Result(
                        summary="Permitted source.", sources=[self.bridge.independent.evidence(row)]
                    ),
                )
                require(self.bridge, owner, selection)
                rows.append(row)
            except DomainError as exc:
                if exc.status == "source_changed":
                    raise
                unavailable = True
        if request.documents and not rows:
            raise DomainError(
                "permission_denied", "This source selection is unavailable for independent use."
            )
        return rows, unavailable

    async def run(self, owner, request):
        self.enabled()
        rows, unavailable = await self.documents(owner, request)
        if request.operation == "obligations":
            result = self.inventory(owner, request, rows)
        elif request.operation == "feedback":
            result = self.feedback(owner, request, rows)
        elif request.operation == "resume":
            result = self.resume(owner, request)
        else:
            result = self.changes(owner, request, rows)
        if unavailable:
            result.status = "partial_data"
            result.data["coverage"] = "partial_selection; some evidence unavailable"
        return self.release(owner, result, operation=request.operation)

    def inventory(self, owner, request, rows):
        work, groups, sources, complete, origins = [], [], [], True, {}
        for row in rows:
            if (
                row.content.get("reviewed_dataset")
                and row.content.get("review", {}).get("source_hash") == row.version_hash
            ):
                dataset = IndependentAcademicInput.model_validate(row.content["reviewed_dataset"])
            else:
                try:
                    raw = (
                        self.bridge.library.bytes(owner, row.id[4:])
                        if row.id.startswith("lib_")
                        else base64.b64decode(row.content["bytes"], validate=True)
                    )
                    if len(raw) > 80_000:
                        raise ValueError
                    dataset = IndependentAcademicInput.model_validate_json(raw)
                except ValueError:
                    complete = False
                    continue
            work.extend(
                w.model_copy(
                    update={
                        "key": scoped_work_id(row.id, w.key),
                        "prerequisites": [scoped_work_id(row.id, p) for p in w.prerequisites],
                        "parent_key": scoped_work_id(row.id, w.parent_key)
                        if w.parent_key
                        else None,
                        "aliases": [scoped_work_id(row.id, a) for a in w.aliases],
                    }
                )
                for w in dataset.work
            )
            groups.extend(
                g.model_copy(
                    update={
                        "key": scoped_work_id(row.id, g.key),
                        "members": [scoped_work_id(row.id, k) for k in g.members],
                        "selected": [scoped_work_id(row.id, k) for k in g.selected],
                    }
                )
                for g in dataset.requirement_groups
            )
            origins.update({scoped_work_id(row.id, w.key): row for w in dataset.work})
            sources.append(self.bridge.independent.evidence(row))
            complete &= dataset.complete
        from canvas_bridge.academic.independent_models import IndependentWork

        for record in self.shared_records(owner, request.course, "task", operation="obligations"):
            value = IndependentWork.model_validate(record.data["value"])
            work.append(value.model_copy(update={"key": record.id, "activity_kind": "personal"}))
            sources.append(self.records.citation(record))
        if not work:
            raise DomainError(
                "needs_input",
                "Review document candidates or add a personal task in settings first.",
            )
        if len(work) > 50:
            raise DomainError(
                "needs_input", "Select fewer documents; this inventory supports fifty activities."
            )
        dataset = IndependentAcademicInput(
            schema_version="independent-academic-1",
            work=work,
            requirement_groups=groups,
            complete=complete and bool(rows),
        )
        source = sources[0].model_copy(update={"course_id": request.course})
        data = obligations(dataset, source, now=self.bridge.retention.clock(), plan=request.plan)
        # Per-activity origin is preserved after combining the bounded inventory.
        records_by_id = {s.id: s for s in sources if s.source_type == "local_study_record"}
        for activity in data["activities"]:
            row = origins.get(activity["key"])
            citation = (
                self.bridge.independent.evidence(row) if row else records_by_id.get(activity["key"])
            )
            if citation:
                activity["source_id"], activity["content_hash"] = citation.id, citation.content_hash
        binding = fingerprint(
            [
                owner,
                request.course,
                [(s.id, s.content_hash) for s in sources],
                data["inventory_hash"],
            ]
        )
        offset = cursor_offset(self.bridge, owner, request.cursor, binding)
        all_activities = data["activities"]
        data["activities"] = all_activities[offset : offset + request.limit]
        data["next_cursor"] = (
            seal_cursor(self.bridge, owner, binding, offset + request.limit)
            if offset + request.limit < len(all_activities)
            else None
        )
        data["page_complete"] = data["next_cursor"] is None
        # Plan/accounting refer to the entire bounded inventory, not just this page.
        data["inventory_hash"] = binding
        return Result(
            status="ok" if dataset.complete else "partial_data",
            summary="Reviewed obligations and a proposal; no official completion or calendar action is asserted.",
            data=data,
            sources=sources,
        )

    def passage(self, selected, rows):
        row = next((r for r in rows if r.id == selected.document_id), None)
        if not row or row.version_hash != selected.expected_hash:
            raise DomainError("source_changed", "Select current evidence from this course.")
        pages = row.content["parsed"].get("pages", [])
        if selected.part > len(pages):
            raise DomainError("needs_input", "The passage locator is unavailable.")
        text = pages[selected.part - 1].get("text", "")
        if selected.end <= selected.start or text[selected.start : selected.end] != selected.quote:
            raise DomainError(
                "source_changed", "The quoted passage does not match its source offsets."
            )
        return row

    def feedback(self, owner, request, rows):
        if not rows:
            raise DomainError(
                "needs_input",
                "Select your own permitted feedback document and its reviewed work link.",
            )
        proposals = request.improvements
        evidence = []
        for row in rows:
            if row.content.get("purpose") != "own_feedback":
                continue
            for part, page in enumerate(row.content["parsed"].get("pages", [])[:5], 1):
                text = page.get("text", "")[:4000]
                if text.strip():
                    evidence.append(
                        {
                            "document_id": row.id,
                            "expected_hash": row.version_hash,
                            "part": part,
                            "start": 0,
                            "end": min(2000, len(text)),
                            "quote": text[:2000],
                            "work_key": row.content.get("feedback_work"),
                            "awarded_points": None,
                        }
                    )
        improvements, observations = [], set()
        for proposal in proposals:
            row = self.passage(proposal.feedback, rows)
            if (
                row.content.get("purpose") != "own_feedback"
                or row.content.get("feedback_work") != proposal.work_key
            ):
                raise DomainError(
                    "needs_input",
                    "Review the explicit own-feedback work link in document settings first.",
                )
            if proposal.reference:
                self.passage(proposal.reference, rows)
            identity = fingerprint([request.course, proposal.work_key, proposal.feedback.quote])
            if identity in observations:
                continue
            observations.add(identity)
            improvements.append(
                proposal.model_dump(mode="json")
                | {
                    "interpretation_status": "host_proposal_not_instructor_statement",
                    "practice_prompt": PRACTICE[proposal.practice],
                    "practice_optional": True,
                    "grade_prediction": None,
                    "saved": False,
                }
            )
        # A supported minimal interpretation for an explicit result/implication comment.
        if not proposals:
            for item in evidence:
                if (
                    item["work_key"]
                    and "result" in item["quote"].casefold()
                    and "implication" in item["quote"].casefold()
                    and re.search(
                        r"\b(describe|explain|separate|distinguish|clarify)\b", item["quote"], re.I
                    )
                ):
                    improvements.append(
                        {
                            "feedback": item,
                            "kind": "suggestion",
                            "action": "Separate the observed result from its implication.",
                            "interpretation_status": "deterministic_suggestion_requires_review",
                            "practice_prompt": PRACTICE["result_implication"],
                            "practice_optional": True,
                            "saved": False,
                        }
                    )
                    break
        repeated = []
        for practice in PRACTICE:
            relevant = [
                p
                for p in proposals
                if p.practice == practice and p.kind in {"suggestion", "required_correction"}
            ]
            works = sorted({p.work_key for p in relevant})
            if len(works) >= 2:
                repeated.append(
                    {
                        "practice": practice,
                        "works": works,
                        "status": "tentative_repeated_observation",
                        "counterexamples": [
                            p.feedback.model_dump(mode="json")
                            for p in proposals
                            if p.practice == practice and p.kind == "praise"
                        ],
                    }
                )
        return Result(
            status="partial_data",
            summary="Own feedback evidence and reviewable improvements; no enduring profile was created.",
            data={
                "feedback_items": evidence[:20],
                "improvements": improvements[:3],
                "repeated_issue": repeated or "not_established",
                "author_role": "student_provided_copy_not_authenticated_instructor",
                "next_action": "Review or reject these interpretations; select optional ungraded practice. Link ambiguous feedback in settings.",
                "limitations": [
                    "Rubric descriptions alone establish neither awarded points nor weaknesses. Host interpretations remain provisional."
                ],
            },
            sources=[self.bridge.independent.evidence(r) for r in rows],
        )

    def resume(self, owner, request):
        goals = self.shared_records(owner, request.course, "goal")
        if request.goal_id:
            goals = [r for r in goals if r.id == request.goal_id]
        if not goals:
            return Result(
                status="needs_input",
                summary="No permitted saved goal is available. Select and explicitly save a goal in study settings.",
                data={"history": "unavailable_or_not_saved"},
            )
        if len(goals) > 1 and not request.goal_id:
            return Result(
                status="needs_input",
                summary="Choose a saved goal to resume.",
                data={
                    "goals": [
                        {"goal_id": r.id, "concept": r.data["value"]["concept"]} for r in goals[:3]
                    ]
                },
                sources=[self.records.citation(r) for r in goals[:3]],
            )
        goal = goals[0]
        attempts = sorted(
            (
                r
                for r in self.shared_records(owner, request.course, "attempt")
                if r.data["value"]["goal_id"] == goal.id
            ),
            key=lambda r: (r.updated_at, r.id),
        )[-5:]
        current = [r for r in attempts if not r.data["value"].get("rejected")]
        last = current[-1].data["value"] if current else None
        exercise = last.get("next_exercise") if last else None
        if (
            last
            and last.get("check") == "control_purpose"
            and last.get("evaluation", {}).get("outcome") == "incomplete"
        ):
            exercise = PRACTICE["control_purpose"]
            if exercise == last["prompt"]:
                exercise = "Generated ungraded practice: a fictional enzyme assay adds solvent to treated samples. Name the comparison and explain what solvent control would reveal."
        return Result(
            summary="Resume from selected saved evidence; no mastery or assignment completion is inferred.",
            data={
                "goal_id": goal.id,
                "concept": goal.data["value"]["concept"],
                "observations": [
                    {"attempt_id": r.id, "event_time": r.updated_at.isoformat(), **r.data["value"]}
                    for r in current
                ],
                "unresolved_issue": last.get("observation")
                if last
                else "No unrejected attempted response is saved.",
                "next_exercise": exercise
                or "Choose a new permitted example and explain the concept in your own words.",
                "minutes": request.minutes,
                "stopping_point": "Attempt one explanation, then stop or choose whether to save the outcome.",
                "mastery_established": False,
                "notifications_created": False,
            },
            sources=[self.records.citation(r) for r in [goal, *current]],
        )

    def changes(self, owner, request, rows, *, local=False):
        state = self.records.state(owner)
        selected = {r.id: r for r in rows}

        def get_records(owner, course, subtype):
            return (
                self.records.rows(owner, course, subtype)
                if local
                else self.shared_records(owner, course, subtype, operation="changes")
            )

        records = get_records(owner, request.course, "import_review")
        if selected:
            records = [r for r in records if any(s.id in selected for s in r.sources)]
        if not records:
            return Result(
                status="needs_input",
                summary="Save a reviewed source version to establish a baseline. No earlier history is assumed.",
                data={"history": "baseline_missing"},
            )
        record_ids = {r.id for r in records}
        revisions = [r for r in state.revisions if r.after and r.after.id in record_ids]
        if request.baseline_revision and not any(
            r.id == request.baseline_revision for r in revisions
        ):
            return Result(
                status="needs_input",
                summary="The requested baseline is unavailable; inspect retained reviewed versions.",
                data={"history": "requested_baseline_unavailable"},
            )
        events, processing, gaps = [], [], False
        plans = get_records(owner, request.course, "plan")
        active = not request.baseline_revision
        for revision in revisions:
            if revision.id == request.baseline_revision:
                active = True
                continue
            if not active or not revision.before:
                continue
            for tag in revision.before.sources:
                if tag.origin != "local_document":
                    continue
                row = self.bridge.independent.require(owner, tag.id)
                known = {row.version_hash} | {
                    h["hash"] for h in row.content.get("version_history", [])
                }
                if tag.version not in known:
                    gaps = True
                    break
            else:
                old_keys = {w["key"] for w in revision.before.data["value"]["dataset"]["work"]}
                new_keys = {w["key"] for w in revision.after.data["value"]["dataset"]["work"]}
                if old_keys - new_keys:
                    gaps = True
                    processing.append(
                        {
                            "revision_id": revision.id,
                            "kind": "missing_records_not_deletion_or_completion",
                        }
                    )
                document_id = next(
                    s.id for s in revision.after.sources if s.origin == "local_document"
                )
                canonical = {scoped_work_id(document_id, key): key for key in new_keys}
                scoped_plans = []
                for plan in plans:
                    blocks = []
                    for block in plan.data["value"].get("blocks", []):
                        raw = block["work_id"]
                        unique_raw = (
                            sum(
                                raw in {w["key"] for w in r.data["value"]["dataset"]["work"]}
                                for r in records
                            )
                            == 1
                        )
                        if raw in canonical or unique_raw:
                            blocks.append(block | {"work_id": canonical.get(raw, raw)})
                    scoped_plans.append(
                        plan.model_copy(update={"data": plan.data | {"value": {"blocks": blocks}}})
                    )
                new_events = transitions(
                    revision.before.data["value"],
                    revision.after.data["value"],
                    revision.id,
                    plans=scoped_plans,
                )
                events.extend(
                    e
                    | {
                        "first_observed_at": revision.created_at.isoformat(),
                        "source_timestamp": None,
                    }
                    for e in new_events
                )
                if not new_events:
                    processing.append(
                        {"revision_id": revision.id, "kind": "no_supported_academic_change"}
                    )
        acks = get_records(owner, request.course, "change_ack")
        for event in events:
            ack = next(
                (a for a in reversed(acks) if a.data["value"]["event_id"] == event["event_id"]),
                None,
            )
            if ack:
                value = ack.data["value"]
                from datetime import datetime

                event["acknowledgment"] = (
                    "unacknowledged"
                    if value["state"] == "snoozed"
                    and value.get("until")
                    and datetime.fromisoformat(value["until"]) <= self.bridge.retention.clock()
                    else value["state"]
                )
        events.sort(
            key=lambda e: (e["category"] != "action_needed", e["first_observed_at"], e["event_id"])
        )
        if len(events) > 100:
            gaps, events = True, events[:100]
        binding = fingerprint(
            [owner, request.course, state.version, [e["event_id"] for e in events]]
        )
        offset = cursor_offset(self.bridge, owner, request.cursor, binding)
        output = events[offset : offset + request.limit]
        return Result(
            status="partial_data" if gaps else "ok",
            summary="On-demand reviewed changes, as of the retained imports. Plans and calendars were not changed.",
            data={
                "events": output,
                "processing_events": processing[:5],
                "coverage": "partial_history" if gaps else "retained_review_transitions_only",
                "history": "baseline_only"
                if not any(r.before for r in revisions)
                else "retained_versions",
                "next_cursor": seal_cursor(self.bridge, owner, binding, offset + len(output))
                if offset + len(output) < len(events)
                else None,
                "delivery": "disabled",
                "external_writes": False,
            },
            sources=[self.records.citation(r) for r in [*records, *plans, *acks]],
        )

"""Separate, read-only configuration stages; no login or approval side effects."""

import os

from sqlalchemy import select

from canvas_bridge.approval_policy import PolicyRequest
from canvas_bridge.storage import Connection, Course, aware


def stages(bridge, owner, institution):
    request = PolicyRequest(
        institution.id, bridge.settings.profile, frozenset({"identity", "courses"}), "local", "link"
    )
    approval = {
        authority: bridge.approval_gateway._evaluate(request, authorities=(authority,))
        for authority in ("provider", "institution", "sharing")
    }
    oauth = bool(
        institution.oauth
        and institution.client_id_env
        and institution.client_secret_env
        and os.environ.get(institution.client_id_env)
        and os.environ.get(institution.client_secret_env)
    )
    enabled = (
        bridge.settings.capability_profile == "institutional_pilot"
        and bridge.settings.live_access_enabled
        and not bridge.synthetic
    )
    with bridge.store.transaction() as session:
        rows = list(
            session.scalars(
                select(Connection).where(
                    Connection.owner == owner, Connection.institution == institution.id
                )
            )
        )
        identity = [bridge.authentication_status(row) for row in rows]
        tokens = [
            "absent"
            if not row.credential
            else "expired"
            if row.token_expires_at and aware(row.token_expires_at) <= bridge.retention.clock()
            else "present_not_probed"
            for row in rows
        ]
        selected = session.scalar(
            select(Course.id)
            .where(
                Course.owner == owner,
                Course.connection_id.in_([r.id for r in rows]),
                Course.selected.is_(True),
            )
            .limit(1)
        )
    return {
        "provider_approval": approval["provider"].state,
        "institution_approval": approval["institution"].state,
        "data_sharing_approval": approval["sharing"].state,
        "deployment_configuration": "enabled_for_evaluation" if enabled else "live_disabled",
        "oauth_client_configuration": "configured_not_authenticated"
        if oauth
        else "operator_setup_required",
        "upstream_identity": ", ".join(identity) if identity else "not_linked",
        "token_validity": ", ".join(tokens) if tokens else "absent",
        "course_scope": "selected_not_refreshed" if selected else "not_selected",
        "link_action_available": enabled
        and oauth
        and all(d.allowed for d in approval.values())
        and institution.status in {"supported", "pilot_supported"},
        "next_action": "Obtain independently documented provider and institutional approval; configure the approved OAuth client; then link, verify identity and select courses. Application sign-in grants none of these approvals.",
    }

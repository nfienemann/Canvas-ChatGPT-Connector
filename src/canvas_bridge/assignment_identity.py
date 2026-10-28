"""Add a semantic comparison hash while retaining the exact minimized payload hash."""

import re
from copy import deepcopy
from html import escape, unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from canvas_bridge.evidence import fingerprint

RAW_FIELDS = (
    "name",
    "description",
    "due_at",
    "unlock_at",
    "lock_at",
    "points_possible",
    "submission_types",
    "updated_at",
    "submission",
)


def without_transport_parameters(url):
    try:
        parsed = urlsplit(url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        stable = [
            (k, v)
            for k, v in query
            if k.lower()
            not in {
                "verifier",
                "access_token",
                "token",
                "signature",
                "expires",
                "x-amz-signature",
                "x-amz-date",
                "x-amz-expires",
                "x-amz-credential",
                "x-amz-security-token",
                "policy",
                "key-pair-id",
            }
        ]
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(stable), parsed.fragment)
        )
    except ValueError:
        return url


def semantic_hash(raw, origin):
    fields = deepcopy(
        {
            k: raw.get(k)
            for k in (*RAW_FIELDS, "rubric", "allowed_extensions", "published", "locked_for_user")
        }
    )
    submission = fields.get("submission")
    if isinstance(submission, dict):
        # A submission-preview URL is transport metadata, not submitted content.
        if isinstance(submission.get("preview_url"), str):
            submission["preview_url"] = without_transport_parameters(submission["preview_url"])
        attachments = submission.get("attachments", [])
        for attachment in attachments if isinstance(attachments, list) else []:
            if (
                isinstance(attachment, dict)
                and attachment.get("id")
                and isinstance(attachment.get("url"), str)
            ):
                attachment["url"] = without_transport_parameters(attachment["url"])
    description = fields.get("description")
    if isinstance(description, str):

        def stable_anchor(match):
            value = unescape(match[2])
            try:
                parsed = urlsplit(value)
                base = urlsplit(origin)
                if parsed.netloc and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
                    return match[0]
                if not re.fullmatch(
                    r"/(?:api/v1/)?(?:courses/[0-9]+/)?files/[0-9]+(?:/(?:download|preview))?/?",
                    parsed.path,
                ):
                    return match[0]
                query = parse_qsl(parsed.query, keep_blank_values=True)
                stable = [(k, v) for k, v in query if k.lower() not in {"verifier", "access_token"}]
                if stable == query:
                    return match[0]
                url = urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, urlencode(stable), parsed.fragment)
                )
                return "href=" + match[1] + escape(url, quote=True) + match[1]
            except ValueError:
                return match[0]

        fields["description"] = re.sub(
            r"""href\s*=\s*(["'])(.*?)\1""", stable_anchor, description, flags=re.I | re.S
        )
    return fingerprint({"schema": "assignment_semantic_v1", "fields": fields})

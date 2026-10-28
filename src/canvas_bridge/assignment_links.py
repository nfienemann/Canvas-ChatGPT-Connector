"""Assignment anchors are untrusted references, never authorization or file contents."""

import asyncio
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.file_download import file_metadata, file_version
from canvas_bridge.normalize import PlainText, canonical_id, plain_text
from canvas_bridge.policy import Endpoint
from canvas_bridge.storage import Material

MAX_LINKS = 20
LINK_SECONDS = 10
FILE_PATH = re.compile(
    r"/(?:api/v1/)?(?:courses/([0-9]+)/)?files/([0-9]+)(?:/(?:download|preview))?/?"
)


class Anchors(PlainText):
    def __init__(self):
        super().__init__()
        self.links = []
        self.anchor = None
        self.count = 0

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "a" and not self.hidden:
            href = dict(attrs).get("href")
            if href:
                self.count += 1
                self.anchor = {"href": href, "label": ""} if len(self.links) < MAX_LINKS else None
                if self.anchor is not None:
                    self.links.append(self.anchor)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "a":
            self.anchor = None

    def handle_data(self, data):
        if self.anchor is not None and not self.hidden:
            self.anchor["label"] = (self.anchor["label"] + data)[:1000]


def references(html, origin, canvas_course):
    parser = Anchors()
    if isinstance(html, str):
        parser.feed(html[:200_004])
    result = []
    for link in parser.links:
        row = {
            "title": link["label"].strip(),
            "state": "unresolved",
            "material_id": None,
            "content_reviewed": False,
            "url": None,
        }
        try:
            url = urlsplit(urljoin(origin + "/", link["href"]))
            if url.scheme not in {"https", "http"} or url.username or url.password:
                raise ValueError("Unsafe link")
            row["url"] = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
            base = urlsplit(origin)
            if (url.scheme, url.netloc) != (base.scheme, base.netloc):
                row["state"] = "external_not_followed"
            elif match := FILE_PATH.fullmatch(url.path):
                linked_course, file_id = match.groups()
                if linked_course is not None and linked_course != canvas_course:
                    row["state"] = "outside_assignment_course"
                else:
                    row.update(state="pending_authorization", _file_id=file_id)
            else:
                row["state"] = "unsupported_canvas_reference"
        except ValueError:
            row.update(state="unsafe_reference", url=None)
        result.append(row)
    return result, parser.count > MAX_LINKS or isinstance(html, str) and len(html) > 200_004


async def resolve_links(bridge, owner, ref, course, client, html):
    rows, truncated = references(html, client.institution.origin, course.source_id)
    deadline = asyncio.get_running_loop().time() + LINK_SECONDS
    for row in rows:
        file_id = row.pop("_file_id", None)
        if file_id is None:
            continue
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            row.update(state="unresolved", reason_code="ASSIGNMENT_LINK_TIME_BUDGET")
            continue
        try:
            conn, _ = bridge.selected(owner, ref, [course.id])
            bridge.authorize(owner, ref, course.id, "files", Endpoint.FILE).require()
            async with asyncio.timeout(remaining):
                metadata = await file_metadata(client, course.source_id, file_id)
            material_id = canonical_id(owner, ref, "file", f"{course.source_id}:{file_id}")
            with bridge.store.transaction() as session:
                current = bridge.store.connection(session, owner, ref, lock=True)
                bridge.authorize(
                    owner, ref, course.id, "files", Endpoint.FILE, session=session
                ).require()
                if current.epoch != conn.epoch:
                    raise DomainError("source_changed", "Scope changed during link resolution.")
                material = session.get(Material, material_id)
                title = plain_text(str(metadata.get("display_name", "Linked file")), 1000)
                canonical_url = (
                    f"{client.institution.origin}/courses/{course.source_id}/files/{file_id}"
                )
                if material is None:
                    material = Material(
                        id=material_id,
                        owner=owner,
                        connection_id=ref,
                        course_id=course.id,
                        source_id=file_id,
                        kind="file",
                        title=title,
                        url=canonical_url,
                        version_hash="",
                        text="",
                        locators=[],
                        limitations=["Not fetched."],
                        file_state={},
                    )
                    session.add(material)
                else:
                    material = bridge.store.owned(session, Material, owner, ref, material_id)
                    if material.course_id != course.id or material.kind != "file":
                        raise DomainError("permission_denied", "File mapping changed.")
                material.file_state = {
                    **material.file_state,
                    "inventory": {
                        "filename": plain_text(str(metadata.get("filename", "")), 1000),
                        "content_type": str(metadata.get("content-type", ""))[:200],
                        "size": metadata.get("size"),
                        "source_version": file_version(metadata),
                    },
                    "inventory_checked_at": utcnow().isoformat(),
                }
            row.update(
                state="resolved",
                material_id=material_id,
                url=canonical_url,
                source_version=file_version(metadata),
                access_verification="course_file_metadata",
                continuation={"tool": "read_course_file", "file_id": material_id},
            )
        except TimeoutError:
            row.update(state="unresolved", reason_code="ASSIGNMENT_LINK_TIME_BUDGET")
        except DomainError as exc:
            if exc.status in {"source_changed", "reconnect_required"}:
                raise
            row.update(
                state="denied" if exc.status == "permission_denied" else "unresolved",
                reason_code=exc.reason_code or "ASSIGNMENT_LINK_UNAVAILABLE",
            )
    return {
        "references": rows,
        "truncated": truncated,
        "scope": "explicit_assignment_anchors_only",
        "linked_content_reviewed": False,
    }

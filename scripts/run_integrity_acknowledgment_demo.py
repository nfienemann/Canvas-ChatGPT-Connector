"""Disposable loopback UI for a human to exercise AI-19; never auto-acknowledges."""

import argparse
import asyncio
import hashlib
import html
import json
import os
import secrets
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.egress_models import RecipientIdentity
from canvas_bridge.integrity.models import Activity, AssistanceRequest, Scope
from canvas_bridge.policy import Registry
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Store
from canvas_bridge.synthetic import SyntheticProvider
from canvas_bridge.vault import Vault

ROOT = Path(__file__).resolve().parents[1]
SILENT = b"SYNTHETIC AI-19 silent-policy variant. Fictional C08 brainstorming exercise. No course AI-use guidance is stated. This variant excludes the higher-level requirement in the original C08 scenario. It is not instructor permission or real coursework."


def implementation_hashes():
    paths = [*sorted((ROOT / "src/canvas_bridge/integrity").glob("*.py")), Path(__file__).resolve()]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
    }


class Demo:
    def __init__(self, bridge, owner, folder, origin):
        self.bridge, self.owner, self.folder, self.origin = bridge, owner, folder, origin
        self.token = secrets.token_urlsafe(32)
        self.path = "/demo/" + self.token
        self.lock = asyncio.Lock()
        self.decision = self.request = self.receipt = None
        self.hashes = implementation_hashes()

    async def initialize(self):
        ident = await self.bridge.independent.ingest(
            self.owner,
            SILENT,
            "AI-19-silent-variant.txt",
            "text/plain",
            own_material=True,
            share_text=True,
        )
        self.request = AssistanceRequest(
            scope=Scope(
                document_ids=[ident],
                local_course="CB_TEST_C08_SILENT",
                assessment_id="fictional-brainstorm",
                institution="synthetic",
            ),
            activity=Activity.BRAINSTORM,
        )
        checked = await self.bridge.integrity.check(self.owner, self.request)
        decision = checked.data["decision"]
        if (
            not decision["acknowledgment_eligible"]
            or decision["allowed"]
            or decision["permission_established"]
        ):
            raise RuntimeError(
                "The disposable scenario is not eligible; no acknowledgment screen opened."
            )
        self.decision = checked

    def page(self, body):
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Canvas Bridge — AI-19 test</title>'
            "<style>body{font:18px/1.6 system-ui;max-width:760px;margin:48px auto;padding:0 24px;color:#17352f;background:#f5f8f7}h1{line-height:1.2}section{background:white;border:1px solid #b8ccc5;border-radius:12px;padding:24px;margin:24px 0}button{font:inherit;padding:12px 20px;background:#174e49;color:white;border:0;border-radius:8px;margin-top:20px}input{width:20px;height:20px}small{color:#48635b}</style>"
            "<h1>Fictional acknowledgment test</h1><p><strong>Disposable synthetic environment. Institutional access is disabled.</strong></p>"
            + body
            + "</html>",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
                # Fetch serializes form POST Origin as null under no-referrer.
                # Same-origin retains the loopback Origin without exposing it elsewhere.
                "Referrer-Policy": "same-origin",
            },
        )

    async def view(self, request):
        if request.headers.get("host") != self.origin.removeprefix("http://"):
            return PlainTextResponse("Host rejected", status_code=403)
        if self.receipt:
            return self.page(
                "<section><h2>Test completed</h2><p>Your acknowledgment applied only to the displayed fictional brainstorming activity. Reuse for submission drafting was rejected. Instructor permission remains unconfirmed.</p></section>"
            )
        notice = html.escape(self.decision.data["acknowledgment_notice"])
        decision = self.decision.data["decision"]
        body = f'<section><h2>Exact activity</h2><p>Brainstorm possible topics for the fictional C08 silent-policy exercise. No draft, outline, answer, submission, or real coursework will be generated.</p><h2>Uncertainty notice</h2><p>{notice}</p><p>This test has complete fictional discovery and no higher-level permission requirement. That setup applies only to this isolated test.</p><small>Decision expires: {html.escape(decision["expires_at"])}<br>Policy fingerprint: {html.escape(decision["policy_version"])}</small></section><form method="post" action="{self.path}"><input type="hidden" name="csrf" value="{self.token}"><label><input type="checkbox" name="acknowledge" value="yes" required> I have read this notice and explicitly acknowledge the uncertainty for this exact fictional brainstorming activity.</label><br><button type="submit">Acknowledge this fictional test only</button></form><p><small>You may leave this page without acknowledging. This does not change your personal Bridge configuration, approvals, or institutional connection.</small></p>'
        result = self.page(body)
        result.set_cookie(
            "demo_session", self.token, httponly=True, samesite="strict", path=self.path
        )
        return result

    async def submit(self, request):
        if request.headers.get("origin") != self.origin or request.headers.get(
            "host"
        ) != self.origin.removeprefix("http://"):
            return PlainTextResponse("Origin rejected", status_code=403)
        if (
            request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            return PlainTextResponse("Form required", status_code=415)
        raw = await request.body()
        if len(raw) > 2048:
            return PlainTextResponse("Form too large", status_code=413)
        from urllib.parse import parse_qs

        form = parse_qs(raw.decode("ascii"), strict_parsing=True)
        if not (
            secrets.compare_digest(request.cookies.get("demo_session", ""), self.token)
            and form.get("csrf") == [self.token]
            and form.get("acknowledge") == ["yes"]
        ):
            return PlainTextResponse("Explicit displayed acknowledgment required", status_code=403)
        async with self.lock:
            if self.receipt:
                return await self.view(request)
            if implementation_hashes() != self.hashes:
                return PlainTextResponse(
                    "Test implementation changed. Restart and review again.", status_code=409
                )
            context = request_authorization.set(
                RequestAuthorization(
                    "integrity-ui-test", egress_identity=RecipientIdentity("chatgpt")
                )
            )
            try:
                acked = await self.bridge.integrity.acknowledge(
                    self.owner, self.decision.data["decision"]["id"], True
                )
                acknowledgment = acked.data["acknowledgment_id"]
                continued = await self.bridge.integrity.prepare(
                    self.owner,
                    self.request.model_copy(update={"acknowledgment_id": acknowledgment}),
                )
                boundary = None
                try:
                    await self.bridge.integrity.prepare(
                        self.owner,
                        self.request.model_copy(
                            update={"activity": Activity.DRAFT, "acknowledgment_id": acknowledgment}
                        ),
                    )
                except DomainError as exc:
                    boundary = exc.reason_code
                decision = continued.data["decision"]
                assert decision["allowed"] and not decision["permission_established"]
                assert boundary == "INTEGRITY_ACKNOWLEDGMENT_SCOPE_MISMATCH"
                self.receipt = {
                    "case_id": "AI-19",
                    "status": "PASS",
                    "interaction": "explicit_human_browser_form",
                    "observed_at": utcnow().isoformat(),
                    "source_sha256": hashlib.sha256(SILENT).hexdigest(),
                    "implementation_hashes": self.hashes,
                    "notice": self.decision.data["acknowledgment_notice"],
                    "activity": "brainstorming",
                    "course": "CB_TEST_C08_SILENT",
                    "allowed_after_acknowledgment": decision["allowed"],
                    "permission_established": decision["permission_established"],
                    "different_activity_reason": boundary,
                    "institutional_access_enabled": False,
                    "scope": "isolated synthetic UI acceptance; not production consent or a reusable acknowledgment",
                }
                (self.folder / "receipt.json").write_text(
                    json.dumps(self.receipt, indent=2), encoding="utf-8"
                )
                self.bridge.integrity.acknowledgment_history(self.owner, acknowledgment)
            except DomainError as exc:
                return self.page(
                    "<section><h2>Recheck required</h2><p>"
                    + html.escape(str(exc))
                    + "</p><p>No successful acknowledgment acceptance was recorded.</p></section>"
                )
            finally:
                request_authorization.reset(context)
        return await self.view(request)

    def app(self):
        return Starlette(
            routes=[Route(self.path, self.view), Route(self.path, self.submit, methods=["POST"])]
        )


async def run(args):
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    key = folder / "vault.key"
    key.write_bytes(os.urandom(32))
    journal = folder / "deletions.jsonl"
    journal.touch()
    origin = f"http://127.0.0.1:{args.port}"
    settings = Settings(
        _env_file=None,
        profile="synthetic",
        capability_profile="offline_research",
        live_access_enabled=False,
        database_url="sqlite:///:memory:",
        vault_key_file=key,
        deletion_journal=journal,
        institutions_file=ROOT / "institutions.json",
        integrity_policy_reviews_file=None,
        resource_url=origin,
        file_reading_enabled=True,
        parser_root=args.parser_root,
    )
    store = Store(settings.database_url)
    store.create_fixture_schema()
    bridge = Bridge(
        settings, store, Vault(key), Registry(settings.institutions_file), SyntheticProvider()
    )
    demo = Demo(bridge, "fictional-ui-test-owner", folder, origin)
    try:
        await demo.initialize()
        (folder / "launch.json").write_text(
            json.dumps({"url": origin + demo.path, "state": "AWAITING_HUMAN_UI_ACKNOWLEDGMENT"}),
            encoding="utf-8",
        )
        await uvicorn.Server(
            uvicorn.Config(
                demo.app(), host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
            )
        ).serve()
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parser-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    asyncio.run(run(parser.parse_args()))

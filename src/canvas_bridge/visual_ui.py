"""Static native ChatGPT page reader. No server, browser or Canvas credentials."""

from pathlib import Path

PAGE_URI = "ui://canvas-bridge/page-reader-v5.html"
PAGE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canvas document reader</title><style>
:root{color-scheme:light dark;font:15px system-ui}body{margin:0;padding:16px}
h2{font-size:18px;margin:0 0 8px}p{line-height:1.45}button{padding:10px 16px;border-radius:8px;border:1px solid #888;cursor:pointer;font:inherit;max-width:100%;overflow-wrap:anywhere}
button:disabled{opacity:.6;cursor:default}img{display:block;max-width:100%;max-height:440px;margin:12px auto;object-fit:contain}
#actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}#countdown-note,#status{font-size:14px}#cancel{background:transparent;color:inherit}small{display:block;margin-top:10px;line-height:1.4}[hidden]{display:none!important}
</style></head><body>
<h2 id="title">Canvas document reader</h2>
<p id="description">Send this page directly to ChatGPT for visual analysis. No manual download or upload required.</p>
<img id="page" alt="Authorized Canvas page or slide" hidden>
<div id="actions"><button id="read" aria-describedby="countdown-note" disabled>Send Page to ChatGPT</button>
<button id="cancel" hidden>Cancel automatic send</button></div>
<p id="countdown-note" hidden></p>
<p id="status" role="status">Starting document reader…</p>
<small id="notice">The button sends this page image to this chat only after its content and recipient policy checks pass. Processing and retention depend on the approved AI environment. Canvas is unchanged. Dates, names and table relationships still need careful review.</small>
<script>__READER_SCRIPT__</script></body></html>""".replace(
    "__READER_SCRIPT__",
    Path(__file__).with_name("assets").joinpath("page-reader.js").read_text(encoding="utf-8"),
)


def register_page_reader(mcp, egress):
    @mcp.resource(
        PAGE_URI,
        name="Canvas document reader",
        mime_type="text/html;profile=mcp-app",
        meta={
            "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
            "openai/widgetDescription": "Authorized page or slide preview with a cancelable 30-second automatic-send countdown while the preview and controls are visible. Send Page to ChatGPT or Send Slide to ChatGPT sends immediately. Cancel automatic send to clarify in chat. An authorized access check precedes image handoff; no manual download or Canvas changes.",
            "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
        },
    )
    def page_reader():
        # Static public code only; private pixels arrive via authenticated tool metadata.
        return egress.public_resource(PAGE_HTML, PAGE_URI)

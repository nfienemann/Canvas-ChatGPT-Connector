"""Static native ChatGPT page reader. No server, browser or Canvas credentials."""

from pathlib import Path

PAGE_URI = "ui://canvas-bridge/page-reader-v3.html"
PAGE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canvas page reader</title><style>
:root{color-scheme:light dark;font:15px system-ui}body{margin:0;padding:16px}
h2{font-size:18px;margin:0 0 8px}p{line-height:1.45}button{padding:10px 16px;border-radius:8px;border:1px solid #888;cursor:pointer;font:inherit}
button:disabled{opacity:.6;cursor:default}img{display:block;max-width:100%;max-height:440px;margin:12px auto;object-fit:contain}
#status{font-size:14px}small{display:block;margin-top:10px;line-height:1.4}
</style></head><body>
<h2 id="title">Canvas page reader</h2>
<p>This page stays connected to its Canvas source. Read it visually in this ChatGPT conversation without downloading it yourself.</p>
<img id="page" alt="Authorized Canvas PDF page" hidden>
<button id="read" disabled>Read page in ChatGPT</button>
<p id="status" role="status">Starting page reader…</p>
<small>The button sends this page image to this chat. ChatGPT file retention applies. Canvas is unchanged. Dates, names and table relationships still need careful review.</small>
<script>__READER_SCRIPT__</script></body></html>""".replace(
    "__READER_SCRIPT__",
    Path(__file__).with_name("assets").joinpath("page-reader.js").read_text(encoding="utf-8"),
)


def register_page_reader(mcp):
    @mcp.resource(
        PAGE_URI,
        name="Canvas PDF page reader",
        mime_type="text/html;profile=mcp-app",
        meta={
            "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
            "openai/widgetDescription": "Authorized PDF page preview. Read page in ChatGPT attaches its image for visual interpretation; no manual download or Canvas changes.",
            "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
        },
    )
    def page_reader():
        # Static public code only; private pixels arrive via authenticated tool metadata.
        return PAGE_HTML

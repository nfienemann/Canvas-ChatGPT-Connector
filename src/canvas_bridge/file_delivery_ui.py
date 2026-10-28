"""Static download card; credentials and bytes arrive only in authenticated metadata."""

from pathlib import Path

DOWNLOAD_URI = "ui://canvas-bridge/original-download-v1.html"


def register_download_card(mcp, egress):
    @mcp.resource(
        DOWNLOAD_URI,
        name="Canvas original file download",
        mime_type="text/html;profile=mcp-app",
        meta={
            "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
            "openai/widgetDescription": "Download the unchanged authorized Canvas original. A prepared file or host handoff is not a confirmed save or conversation attachment.",
            "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
        },
    )
    def download_card():
        script = (
            Path(__file__)
            .with_name("assets")
            .joinpath("original-download.js")
            .read_text(encoding="utf-8")
        )
        return egress.public_resource(
            (
                """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Download original</title>
<style>:root{font:15px system-ui;color-scheme:light dark}body{padding:18px;margin:0}h2{font-size:18px;overflow-wrap:anywhere}p{line-height:1.5}button{font:inherit;padding:10px 14px;margin:4px;border:1px solid #888;border-radius:8px;cursor:pointer}button:disabled{opacity:.5;cursor:default}#details{color:gray}</style>
</head><body><h2 id="title">Original Canvas file</h2><p id="details"></p>
<button id="download" disabled>Download original</button>
<button id="external" hidden disabled>Download in browser</button>
<button id="fresh" disabled>Get a fresh download</button>
<button id="canvas" disabled>Open in Canvas</button>
<p id="status" role="status">Connecting to your download…</p>
<script>"""
                + script
                + "</script></body></html>"
            ),
            DOWNLOAD_URI,
        )

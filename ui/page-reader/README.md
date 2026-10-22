# Native PDF page reader

This is a static MCP Apps view inside ChatGPT, not a separate application or
service. Node is required only to rebuild the checked-in browser asset:

```sh
npm ci --ignore-scripts
npm run build
```

The locked MCP Apps SDK handles the initialization handshake and authenticated
tool calls. No CDN, external fonts, direct browser fetches, or model API key are
used. CI rebuilds the asset and checks for differences. Bundled dependency
licenses are generated alongside it and included in wheels/native bundles.

The button reauthorizes the selected page, binds the original PDF hash, and
validates the PNG digest. It negotiates image model-context support; otherwise
it uses ChatGPT's documented `uploadFile` and `setWidgetState.imageIds` helpers.
The source/receipt remain attached to the image. Source text is never executed.
An image transfer is not a verified interpretation. ChatGPT must inspect it and
preserve uncertain names, dates, colors and merged-cell relationships.

The page can receive image bytes either in the full MCP result's ImageContent
or private metadata. Initial text-only results still enable a fresh authorized
render; missing image bytes at that final stage fail closed. No Canvas download
URL or credential is passed to the view. ChatGPT retains the sent page according
to its chat/file retention; it is not deliberately saved to the file library.

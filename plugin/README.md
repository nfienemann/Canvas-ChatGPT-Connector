# ChatGPT connection packaging

The executable integration is the authenticated MCP endpoint at the deployed
resource origin plus `/mcp`. Domain tools do not require a custom UI component.

No installable public plugin manifest is emitted with a fake production URL.
Once a supported HTTPS deployment, external issuer, real ChatGPT trial and
distribution eligibility exist, package using the then-current official
[plugin packaging contract](https://developers.openai.com/plugins/build/plugins).
Register the exact host-supplied OAuth callback and record the tested client.

The local synthetic token is for the executable MCP client demonstration only;
it is not a supported ChatGPT authentication scheme or public OAuth issuer.

## Original plugin icon

`assets/canvas-bridge-icon.png` is the original folded-book bridge artwork for
the plugin listing and composer mention. It was generated with the built-in
image-generation tool; the exact prompt is in `assets/icon-prompt.txt`. No OpenAI
or Instructure assets were supplied or reused. The PNG is 1254 by 1254 pixels,
1,235,199 bytes, and works against light and dark host surfaces.

`assets/interface-icons.json` supplies the four documented interface fields:
`logo`, `logoDark`, `composerIcon`, and `composerIconDark`. Merge these into the
existing plugin interface. Paths are relative to the plugin package root.
See the official [branding asset contract](https://developers.openai.com/plugins/deploy/submission#icons-and-screenshots).

On October 23, 2026, the installed Canvas Bridge Personal package was downloaded
through ChatGPT's own UI and updated through **Upload new version**. Version
1.0.1 added the artwork and icon fields to the existing compatibility manifest;
version 1.0.2 also included the current portable root manifest with the same
metadata. Both uploads returned **New version uploaded**. The original registered
app mapping was preserved byte-for-byte. Original and updated private packages
are kept under ignored `.local/plugin-branding/`, outside source control.

Validation: PNG decoding, square dimensions, file-size limits, ZIP integrity,
referenced asset inclusion, manifest consistency, unchanged app mapping, and
`git diff --check -- plugin` passed. No runtime code changed, so the application
test suite was not rerun.

**Visual acceptance remains pending:** ChatGPT displayed version 1.0.2 but still
rendered its placeholder on the plugin detail page and in an unsent composer
mention. Downloaded copies of versions 1.0.1 and 1.0.2 retained all four icon
fields and the artwork; version 1.0.2 retained the portable manifest unchanged
and normalized the compatibility manifest by adding an empty keywords array.
Package acceptance is not proof that ChatGPT has adopted the icon.
After the owner signed in, the official developer dashboard displayed only its
submission onboarding and no existing private-plugin entry or branding control.
No server restart, tool refresh, reconnect, permission change, or public-directory
submission was performed. The requested visible listing and mention icon remain
unverified; do not describe the successful package upload as visual completion.

## Discussion reading tools

The local catalog adds `list_course_discussions`, `read_discussion_topic` and
`get_my_discussion_participation`. Use exact discovered topic/course IDs and
preserve partial, restricted and ambiguous results. `refresh=true` requests fresh
evidence; every current discussion read is uncached. Do not infer missing work
from unavailable entries or equate participation with rubric satisfaction.
`authorized_thread` is blocked pending separate disclosure authorization.
See [the implementation contract](../docs/discussion-reading.md).

"""Publish verified preview assets with the workflow's short-lived repository token."""

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request(url, token, data=None, content_type="application/json", method=None):
    if not url.startswith(("https://api.github.com/", "https://uploads.github.com/")):
        raise ValueError("Unexpected GitHub API origin")
    req = urllib.request.Request(  # noqa: S310 - origins fixed above
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": content_type,
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:  # noqa: S310
        if response.status == 204:
            return None
        return json.load(response)


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    if repository != "nfienemann/Canvas-ChatGPT-Connector":
        raise RuntimeError("Publishing is restricted to the authorized repository.")
    sha = os.environ["GITHUB_SHA"]
    token = os.environ["GITHUB_TOKEN"]
    tag = "demo-" + sha[:12]
    folder = Path("release-assets")
    files = sorted(
        file for file in folder.rglob("*") if file.is_file() and file.name != "SHA256SUMS.txt"
    )
    names = [file.name for file in files]
    expected = {
        "CanvasBridgeDemo-Windows-x64-Setup.exe",
        "CanvasBridgeDemo-macOS-arm64.dmg",
        "CanvasBridgeDemo-macOS-x64.dmg",
        "CanvasBridgeDemo-Linux-x64.deb",
        "CanvasBridgeDemo-Linux-x64.tar.gz",
    }
    if len(names) != len(set(names)) or not expected.issubset(names):
        raise RuntimeError("Missing or duplicate native package assets.")
    verification = [file for file in files if file.name.startswith("verification-")]
    if len(verification) != 4:
        raise RuntimeError("All four native package verification reports are required.")
    for file in verification:
        report = json.loads(file.read_text(encoding="utf-8"))
        if report["wizard"]["native_wizard"] != "passed" or report["mcp"]["planning"] != "verified":
            raise RuntimeError("A native package did not pass its verification.")
    checksums = folder / "SHA256SUMS.txt"
    lines = []
    for file in files:
        with file.open("rb") as stream:
            lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {file.name}\n")
    checksums.write_text("".join(lines), encoding="utf-8")
    files.append(checksums)
    base = f"https://github.com/{repository}/releases/download/{tag}/"
    body = """Try the local demo without installing Python, Git or a command-line tool.

**Fictional courses only.** This preview does not connect to a university or to ChatGPT. Students using a future hosted release should not need to install a server.

| Your computer | Download | Open it |
|---|---|---|
"""
    for label, name, instruction in [
        (
            "Windows 10/11, x64",
            "CanvasBridgeDemo-Windows-x64-Setup.exe",
            "Run the setup wizard, then open Canvas Bridge Demo.",
        ),
        (
            "Mac with Apple silicon, macOS 14+",
            "CanvasBridgeDemo-macOS-arm64.dmg",
            "Drag Canvas Bridge Demo to Applications, then open it.",
        ),
        (
            "Mac with Intel, macOS 15+",
            "CanvasBridgeDemo-macOS-x64.dmg",
            "Drag Canvas Bridge Demo to Applications, then open it.",
        ),
        (
            "Ubuntu 22.04+ / compatible Debian, x64",
            "CanvasBridgeDemo-Linux-x64.deb",
            "Open with your software installer, then launch from Applications.",
        ),
    ]:
        body += f"| {label} | [Download]({base}{name}) | {instruction} |\n"
    body += """
Choose **Set up local demo → Start local demo → Open demo settings**. Use the clearly labeled synthetic sign-in. **Check study tools** runs a real local connection and study-planning check. Closing the launcher stops the service. Upgrades and uninstall keep your separate demo data folder.

These are **unsigned development packages**. Windows or macOS may block them or show publisher warnings. No security settings need to be weakened as part of setup; signed Windows releases and Apple notarization remain required before general student distribution. Linux's package installer may request administrator approval. The portable Linux archive is for other compatible glibc systems; it is not verified on every distribution.

The attached reports cover packaged startup, native wizard controls, MCP reads/planning, and data preservation on the named runner operating systems. They do not establish accessibility certification, OS trust approval, a live Canvas integration, or ChatGPT Directory approval. Checksums detect download corruption; they do not replace publisher signing.
"""
    api = f"https://api.github.com/repos/{repository}"
    try:
        release = request(f"{api}/releases/tags/{tag}", token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        release = request(
            f"{api}/releases",
            token,
            json.dumps(
                {
                    "tag_name": tag,
                    "target_commitish": sha,
                    "name": "Canvas Bridge · Local demo preview",
                    "body": body,
                    "draft": True,
                    "prerelease": True,
                }
            ).encode(),
        )
    if not release["draft"]:
        raise RuntimeError("This preview is already public; do not replace its verified assets.")
    upload_url = release["upload_url"].split("{")[0]
    # A retry may leave an incomplete draft. Replace its assets together so checksums
    # always describe this build; never alter a published preview.
    for asset in release.get("assets", []):
        request(f"{api}/releases/assets/{asset['id']}", token, method="DELETE")
    for file in files:
        request(
            f"{upload_url}?name={urllib.parse.quote(file.name)}",
            token,
            file.read_bytes(),
            "application/octet-stream",
        )
    # Publish only once every platform's upload has succeeded.
    release = request(
        f"{api}/releases/{release['id']}",
        token,
        json.dumps({"draft": False, "body": body}).encode(),
        method="PATCH",
    )
    print(release["html_url"])


if __name__ == "__main__":
    main()

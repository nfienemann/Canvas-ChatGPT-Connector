"""Inspect lockfiles/installed metadata without importing dependency code."""

import argparse
import base64
import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from license_expression import get_spdx_licensing

ALLOWED = {
    "MIT",
    "MIT-0",
    "MIT-CMU",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "PSF-2.0",
    "ISC",
    "0BSD",
}
# Conditions are in docs/supply-chain-security.md; these are technical inventory
# decisions, not a grant of rights or an institutional approval.
CONDITIONAL = {"MPL-2.0", "LGPL-3.0-only"}
CLASSIFIERS = {
    "MIT License": "MIT",
    "Apache Software License": "Apache-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
REVIEWED = {
    ("colorama", "0.4.6"): ("BSD License", "BSD-3-Clause"),
    ("httpx", "0.28.1"): ("BSD License", "BSD-3-Clause"),
    ("pyinstaller", "6.22.0"): (
        "GNU General Public License v2 (GPLv2)",
        "LicenseRef-PyInstaller-Build-Tool-Review",
    ),
    ("pyinstaller-hooks-contrib", "2026.9"): (
        "Apache Software License; GNU General Public License v2 (GPLv2)",
        "LicenseRef-PyInstaller-Hooks-Build-Tool-Review",
    ),
    ("pypdfium2", "5.14.0"): (
        "BSD-3-Clause, Apache-2.0, dependency licenses",
        "LicenseRef-PDFium-Bundle-Review",
    ),
}


def allowed_license(value):
    try:
        expression = get_spdx_licensing().parse(value, validate=True, strict=True)
        symbols = {str(symbol) for symbol in expression.get_symbols()}
    except Exception:
        return False
    # Conservative: both branches of an OR must be approved by this policy.
    return bool(symbols) and symbols <= ALLOWED | CONDITIONAL


def check_locks(root):
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    for package in lock["package"]:
        source = package.get("source", {})
        if source == {"editable": "."} and package["name"] == "canvas-bridge":
            continue
        if source != {"registry": "https://pypi.org/simple"}:
            raise ValueError("Unreviewed Python dependency source.")
        artifacts = package.get("wheels", []) + ([package["sdist"]] if package.get("sdist") else [])
        if not artifacts or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", a.get("hash", "")) for a in artifacts
        ):
            raise ValueError("Dependency artifact lacks a SHA-256 pin.")
        if any(
            not a.get("url", "").startswith("https://files.pythonhosted.org/") for a in artifacts
        ):
            raise ValueError("Unreviewed Python artifact host.")
    npm = json.loads((root / "ui/page-reader/package-lock.json").read_text(encoding="utf-8"))
    for path, package in npm["packages"].items():
        if not path:
            continue
        if not package.get("resolved", "").startswith("https://registry.npmjs.org/") or package.get(
            "link"
        ):
            raise ValueError("Unreviewed Node dependency source.")
        integrity = package.get("integrity", "")
        if not integrity.startswith("sha512-"):
            raise ValueError("Node dependency lacks SHA-512 integrity.")
        if len(base64.b64decode(integrity[7:], validate=True)) != 64:
            raise ValueError("Invalid Node dependency integrity.")
    return lock, npm


def license_report(lock, npm):
    rows, denied = [], []
    for package in lock["package"]:
        name, version = package["name"], package["version"]
        if name == "canvas-bridge":
            continue  # Owner's license decision stays in LICENSE-STATUS.md.
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            rows.append(
                {"name": name, "version": version, "status": "not_installed_on_this_platform"}
            )
            continue
        m = dist.metadata
        declared = (
            m.get("License-Expression")
            or "; ".join(
                c.rsplit(" :: ", 1)[-1]
                for c in m.get_all("Classifier", [])
                if c.startswith("License ::")
            )
            or m.get("License", "UNKNOWN").splitlines()[0]
        )
        license_id = CLASSIFIERS.get(declared, declared)
        reviewed = REVIEWED.get((name, version))
        exception = bool(reviewed and declared == reviewed[0])
        if exception:
            license_id = reviewed[1]
        files = []
        for path in dist.files or []:
            if ".dist-info/" in str(path) and any(
                word in str(path).lower() for word in ("license", "copying", "notice")
            ):
                file = dist.locate_file(path)
                if file.is_file():
                    files.append(
                        {
                            "path": str(path).replace("\\", "/"),
                            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                        }
                    )
        passed = dist.version == version and (
            allowed_license(license_id) or (exception and bool(files))
        )
        rows.append(
            {
                "name": name,
                "version": version,
                "license": license_id,
                "status": "conditional_review"
                if exception or any(x in license_id for x in CONDITIONAL)
                else "allowed"
                if passed
                else "blocked",
                "license_files": files,
            }
        )
        if not passed:
            denied.append(name)
    for path, package in npm["packages"].items():
        if not path:
            continue
        value = package.get("license", "UNKNOWN")
        passed = allowed_license(value)
        rows.append(
            {
                "name": path,
                "version": package["version"],
                "license": value,
                "status": "allowed" if passed else "blocked",
            }
        )
        if not passed:
            denied.append(path)
    return {
        "packages": rows,
        "blocked": denied,
        "limitations": "Metadata screening only. Native libraries, packaging and distribution obligations require release review; absent platform packages require that platform's gate.",
    }


def add_node_sbom(bom, npm):
    refs = {
        path: "npm:" + (path or "page-reader") + "@" + p["version"]
        for path, p in npm["packages"].items()
    }
    for path, p in npm["packages"].items():
        name = path.rsplit("node_modules/", 1)[-1] if path else npm["name"]
        component = {
            "type": "library",
            "bom-ref": refs[path],
            "name": name,
            "version": p["version"],
        }
        if path:
            component["purl"] = "pkg:npm/" + name + "@" + p["version"]
            component["hashes"] = [
                {"alg": "SHA-512", "content": base64.b64decode(p["integrity"][7:]).hex()}
            ]
            if p.get("license"):
                component["licenses"] = [{"expression": p["license"]}]
        bom.setdefault("components", []).append(component)
        dependencies = []
        for name in {
            **p.get("dependencies", {}),
            **p.get("devDependencies", {}),
            **p.get("optionalDependencies", {}),
        }:
            parent = path
            while True:
                child = (parent + "/" if parent else "") + "node_modules/" + name
                if child in refs:
                    dependencies.append(refs[child])
                    break
                if not parent:
                    raise ValueError("Unresolved Node SBOM dependency.")
                parent = parent.rsplit("/node_modules/", 1)[0] if "/node_modules/" in parent else ""
        bom.setdefault("dependencies", []).append(
            {"ref": refs[path], "dependsOn": sorted(set(dependencies))}
        )
    for entry in bom["dependencies"]:
        if entry["ref"] == bom["metadata"]["component"]["bom-ref"]:
            entry.setdefault("dependsOn", []).append(refs[""])
    return bom


def stage_source(root, destination):
    # A fresh fixed subdirectory, never a live data directory or broad filesystem scan.
    if destination.exists():
        raise ValueError("Use a new security scan staging directory.")
    destination.mkdir(parents=True)
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],  # noqa: S607
        cwd=root,
    )  # noqa: S603
    for item in output.decode("utf-8").split("\0"):
        if not item:
            continue
        source = root / item
        if not source.exists():
            continue
        if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()):
            raise ValueError("Unsafe source scan path.")
        target = destination / item
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/security"))
    parser.add_argument("--python-sbom", type=Path)
    parser.add_argument("--stage", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path.cwd()
    lock, npm = check_locks(root)
    report = license_report(lock, npm)
    (args.output / "licenses.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if args.python_sbom:
        bom = add_node_sbom(json.loads(args.python_sbom.read_text(encoding="utf-8")), npm)
        (args.output / "sbom.cdx.json").write_text(
            json.dumps(bom, indent=2) + "\n", encoding="utf-8"
        )
    if args.stage:
        stage_source(root, args.output / "source")
    print(
        f"License metadata checked: {len(report['packages'])}; blocked: {len(report['blocked'])}."
    )
    if report["blocked"]:
        print("Review required: " + ", ".join(report["blocked"]))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

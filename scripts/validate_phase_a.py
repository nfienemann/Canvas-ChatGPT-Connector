"""Validate canonical bytes, normalizing the upstream manifest comparison on Windows."""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=["a", "b", "c", "d", "e", "f"], default="a")
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(exist_ok=True, parents=True)
    packages = {
        "f": (
            "phase_f_handoffs",
            "817dd2bb1e29ea0df7649531aa03629b110307ffc7243fd57bc28716b115e320",
        ),
        "e": (
            "phase_e_resources",
            "07395db2215214d78c6f7a657dd625f56f2ae4d481daa45fa8f63f42623a73a0",
        ),
        "d": (
            "phase_d_forecasting",
            "eab5c2c19bb783268bac53e3d0f74336698c73125bb5218f9d41c1e769820761",
        ),
        "c": (
            "phase_c_reconciliation",
            "406a1f7f0451efd8a5aee0155c552d8ddf99aa64b9c59ca2018e2804eca9e126",
        ),
        "a": (
            "phase_a_baseline",
            "99350fab359158a14c471a8f8b028badcd5ccc3b4b7e96f7814a51a1a496d899",
        ),
        "b": (
            "phase_b_readiness",
            "1ffd5be0cfd959aae0efa463d5e543230ad2bc2ae95627d9c0f52f24dd3fa5c6",
        ),
    }
    directory, expected = packages[options.phase]
    bundle = (
        Path(__file__).resolve().parents[1] / f"benchmarks/academic/phase-{options.phase}/specs.zip"
    )
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Unexpected Phase {options.phase.upper()} package")
    with tempfile.TemporaryDirectory() as temp, ZipFile(bundle) as archive:
        archive.extractall(temp)
        root = Path(temp) / directory
        for relative, report in [
            ("validate_package.py", "package"),
            ("fixtures/validate_fixtures.py", "fixture"),
        ]:
            path = root / relative
            args = [sys.executable, "-X", "utf8", "-B", str(path)]
            if os.name == "nt" and report == "package":
                # Adapt only the inventory path spelling. All digests still cover canonical bytes.
                source = path.read_text("utf-8").replace(
                    "str(path.relative_to(root))", "path.relative_to(root).as_posix()"
                )
                args = [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-B",
                    "-c",
                    "import sys\n__file__=sys.argv.pop(1)\n" + source,
                    str(path),
                ]
            subprocess.run(  # noqa: S603 - hash-pinned packaged validator
                [
                    *args,
                    "--negative-controls",
                    "--output"
                    if options.phase in {"e", "f"} and report == "fixture"
                    else "--report",
                    str(output / f"{report}-checks.json"),
                ],
                check=True,
            )


if __name__ == "__main__":
    main()

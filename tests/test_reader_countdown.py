"""Deterministic countdown/lifecycle checks using synthetic image bytes."""

import shutil
import subprocess

import pytest


@pytest.mark.parametrize(
    "scenario",
    [
        "pdf",
        "pptx",
        "fallback",
        "cancel",
        "manual",
        "visibility",
        "suspend",
        "loading",
        "denied",
        "changed",
        "messageFails",
        "cancel_refresh",
        "cancel_digest",
        "new_preview",
        "globals",
        "noState",
        "stateFails",
        "unsupported",
    ],
)
def test_reader_countdown(scenario):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node runtime needed for the native UI bridge contract")
    run = subprocess.run(  # noqa: S603 - fixed trusted harness, synthetic fixtures only.
        [node, "tests/page_reader_countdown.mjs", scenario],
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr

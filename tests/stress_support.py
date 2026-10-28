"""Offline adapter for the versioned, fictional October 28 stress corpus.

Gold answers never enter this adapter or the import store. Native records remain
per-course; unsupported facts remain in a hash-bound sidecar instead of a text blob.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field

from canvas_bridge.academic.independent_models import IndependentAcademicInput
from canvas_bridge.domain import Model

ROOT = Path(__file__).parent / "fixtures" / "stress-repair"
NOW = datetime(2026, 10, 28, 18, tzinfo=UTC)


class Assessment(Model):
    id: str
    earned: Decimal | None
    possible: Decimal = Field(gt=0)
    state: Literal["graded", "ungraded"]


class Points(Model):
    assessments: list[Assessment] = Field(min_length=1, max_length=100)
    target_percent: Decimal = Field(ge=0, le=100)


class NeutralRecords(Model):
    fixture_schema: Literal["canvas-bridge-stress-fixture-1"] = Field(alias="schema")
    synthetic: Literal[True]
    native_import_compatibility: str
    points: Points
    weighted: dict
    drop_lowest_percentage: dict
    extra_credit: dict
    capacity: dict
    discussion: dict
    figure: dict
    prerequisites: dict[str, list[str]]
    proposed_courses: list[str]
    verified_completed_courses: list[str]
    catalog_year: str | None


def load_records():
    raw = (ROOT / "schema_neutral_records.json").read_bytes()
    return NeutralRecords.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def adapt(course, variant=None):
    records, digest = load_records()
    native = {"schema_version": "independent-academic-1", "complete": False}
    locators = {}
    if course in {"C01", "C02", "C03"}:
        grades = {
            "method": "points",
            "complete": True,
            "groups": [{"id": "points", "name": "Fictional points"}],
            "assessments": [],
        }

        def score(key, earned, possible, group="points", locator=""):
            grades["assessments"].append(
                {
                    "id": key,
                    "title": key,
                    "group_id": group,
                    "possible": str(possible),
                    "score": None if earned is None else str(earned),
                    "score_state": "ungraded" if earned is None else "posted",
                    "eligibility_verified": True,
                }
            )
            locators[key] = "schema_neutral_records.json#" + locator

        if course == "C01":
            for index, row in enumerate(records.points.assessments):
                if (row.state == "ungraded") != (row.earned is None):
                    raise ValueError("Unknown scores must remain unknown.")
                score(row.id, row.earned, row.possible, locator=f"/points/assessments/{index}")
        elif course == "C02":
            grades.update(method="weighted", groups=[])
            for group, pairs in records.weighted["categories"].items():
                grades["groups"].append(
                    {
                        "id": group,
                        "name": group,
                        "weight": str(Decimal(records.weighted["weights"][group]) * 100),
                    }
                )
                for index, (earned, possible) in enumerate(pairs):
                    score(
                        f"{group}-{index}",
                        None if variant == "empty" and group == "exams" else earned,
                        possible,
                        group,
                        f"/weighted/categories/{group}/{index}",
                    )
            if variant == "review":
                grades.update(
                    policy_origin="syllabus_interpretation",
                    rules=["Fixture weighted policy requires review."],
                )
        elif variant == "bonus":
            data = records.extra_credit
            score("base", data["earned_base"], data["possible_base"], locator="/extra_credit")
            score("bonus", data["bonus_earned"], 0, locator="/extra_credit/bonus_earned")
        else:
            grades["groups"][0]["drop_lowest"] = records.drop_lowest_percentage["drop_count"]
            grades["groups"][0]["drop_basis"] = "percentage"
            for index, (earned, possible) in enumerate(records.drop_lowest_percentage["scores"]):
                score(
                    f"Quiz-{chr(65 + index)}",
                    earned,
                    possible,
                    locator=f"/drop_lowest_percentage/scores/{index}",
                )
            if variant == "nonlinear":
                grades["unsupported_rules"] = ["Nonlinear alternative policy is unsupported."]
        native["grades"] = grades
    elif course == "C10":
        native["timezone"] = "America/New_York"
        native["work"] = [
            {
                "key": f"task-{index}",
                "title": f"Fictional task {index}",
                "due": {"kind": "local_date", "local_date": "2026-11-01"},
                "effort": {
                    "minimum_minutes": low,
                    "maximum_minutes": high,
                    "origin": "student_estimate",
                    "as_of": NOW.isoformat(),
                },
            }
            for index, (low, high) in enumerate(
                zip(
                    records.capacity["effort_lower_minutes"],
                    records.capacity["effort_upper_minutes"],
                    strict=True,
                )
            )
        ]
        locators = {
            w["key"]: f"schema_neutral_records.json#/capacity/{i}"
            for i, w in enumerate(native["work"])
        }
        if variant == "unknown_effort":
            native["work"].append({"key": "unknown", "title": "Unknown effort"})
    # Complete is deliberately false: this package is a selected subset of a course.
    validated = IndependentAcademicInput.model_validate(native)
    sidecar = {
        "course": course,
        "term": "synthetic Fall 2026",
        "source_sha256": digest,
        "locators": locators,
        "coverage": "selected_fixture_records_only",
        "unmapped_sections": [
            "discussion",
            "figure",
            "prerequisites",
            "proposed_courses",
            "verified_completed_courses",
            "catalog_year",
        ],
    }
    return validated.model_dump(mode="json"), sidecar


def course_sources(course):
    manifest = json.loads((ROOT / "course_manifest.json").read_text())
    item = next(c for c in manifest if c["course_id"] == "CB_TEST_" + course)
    return [ROOT / p.removeprefix("fixtures/") for p in item["files"]]

"""Host authorization surrounds every invocation. Untrusted modules are bounded data."""

import hashlib
import json
import time
from decimal import Decimal

from pydantic import ValidationError

from canvas_bridge.academic.contracts import compatible, unsupported
from canvas_bridge.academic.gateway import denied
from canvas_bridge.academic.services import calculate_grade
from canvas_bridge.extensions.interpreter import evaluate
from canvas_bridge.extensions.models import ExtensionManifest


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


class ExtensionRegistry:
    """Explicit host-owned registration; no entry point discovery or MCP mutator."""

    def __init__(self, *, timer=time.monotonic):
        self._modules = {}
        self._timer = timer

    def register(self, document: bytes):
        if type(document) is not bytes or len(document) > 64_000 or len(self._modules) >= 32:
            unsupported("The extension registry budget was exceeded.")
        try:
            manifest = ExtensionManifest.model_validate(
                json.loads(document, object_pairs_hook=unique_object)
            )
        except (ValidationError, ValueError, RecursionError, UnicodeError):
            unsupported("The extension manifest is invalid or incompatible.")
        key = (manifest.module_id, manifest.module_version)
        if key in self._modules:
            unsupported("An extension version cannot be overwritten.")
        for vector in manifest.tests:
            result = evaluate(manifest, vector.inputs, timer=self._timer)
            if set(result) != set(vector.expected) or any(
                Decimal(result[k]) != v for k, v in vector.expected.items()
            ):
                unsupported("An extension deterministic test failed.")
        # Store immutable serialized content, not a caller-mutable object graph.
        frozen = manifest.model_dump_json().encode()
        self._modules[key] = frozen
        return {
            "module_id": key[0],
            "module_version": key[1],
            "sha256": hashlib.sha256(frozen).hexdigest(),
            "tests_passed": len(manifest.tests),
        }

    def describe(self, module_id, version):
        if (module_id, version) not in self._modules:
            unsupported("The exact requested extension version is not registered.")
        return ExtensionManifest.model_validate_json(self._modules[module_id, version])

    def execute(self, module_id, version, gateway, authorized, *, assumptions):
        # Validate the receipt before any data projection or module invocation.
        dataset = gateway.consume(authorized)
        manifest = self.describe(module_id, version)
        compatible(manifest.sdk_version)
        discovery = gateway.provider.describe()
        for operation in manifest.required_capabilities:
            capability = discovery.operations[operation]
            if not capability.supported or not {
                "courses",
                "categories",
                "assessments",
                "grading_rules",
            } <= set(capability.available_fields):
                unsupported("This provider lacks required grade fields.")
        request = authorized._request
        if authorized._operation not in manifest.required_capabilities:
            denied()
        if request.purpose not in manifest.permission_requirements or any(
            request.purpose not in r.permission.scope for r in dataset.records()
        ):
            denied()
        if type(assumptions) is not dict or set(assumptions) != {
            "future_possible_points",
            "future_score_percent",
        }:
            unsupported("Explicit future points and expected percentage assumptions are required.")
        rules = dataset.grading_rules
        # v1 deliberately models an aggregate points scenario, never weighted/drop rules.
        usable = (
            len(dataset.courses) == 1
            and dataset.complete
            and rules is not None
            and rules.method == "points"
            and not rules.blockers
            and all(not (g.drop_lowest or g.drop_highest) for g in dataset.categories)
        )
        calculation = calculate_grade(gateway, authorized)["calculation"] if usable else None
        values = None
        if calculation and calculation["calculated_percentage"] is not None:
            inputs = {
                "earned_points": sum(
                    (Decimal(c["earned_points"]) for c in calculation["categories"]), Decimal(0)
                ),
                "possible_points": sum(
                    (Decimal(c["possible_points"]) for c in calculation["categories"]), Decimal(0)
                ),
                **assumptions,
            }
            values = evaluate(manifest, inputs, timer=self._timer)
        # Revocation, policy/classification changes and expiry during execution still deny.
        gateway.release(authorized)
        return {
            "schema_version": "academic-extension-result-1",
            "sdk_version": manifest.sdk_version,
            "module": {
                "id": module_id,
                "version": version,
                "sha256": hashlib.sha256(self._modules[module_id, version]).hexdigest(),
            },
            "status": "hypothetical_scenario" if values is not None else "indeterminate",
            "values": values,
            "assumptions": {key: str(value) for key, value in assumptions.items()}
            if values is not None
            else {},
            "sources": [r.provenance.model_dump(mode="json") for r in dataset.records()],
            "restrictions": [r.restrictions.model_dump(mode="json") for r in dataset.records()],
            "complete": dataset.complete,
            "limitations": [
                *dataset.limitations,
                "Aggregate additional-points scenario; future scores and total points are user assumptions, not source facts.",
                "Weighted policies, drop rules and incomplete evidence are unsupported in projection v1.",
            ],
            "verification": "bounded_arithmetic_and_registered_vectors_only_not_instructor_policy_verification",
        }

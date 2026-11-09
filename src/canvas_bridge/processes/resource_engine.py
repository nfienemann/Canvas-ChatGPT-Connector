"""Resource scheduling arithmetic adapted from the supplied Phase E policy.

All inputs come through the typed resource models. The runtime proposes and checks
placements; it does not read fixtures or simulate provider receipts.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from canvas_bridge.analytics.effort_history import union
from canvas_bridge.evidence import fingerprint
from canvas_bridge.planning_dates import instant as utc
from canvas_bridge.processes.resource_models import Inventory, Process, Schedule, Span


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return utc(result)


def minutes(start, end):
    delta = end - start
    return number(Decimal(delta // timedelta(microseconds=1)) / 60_000_000)


def quantity(value):
    return Decimal(str(value))


def number(value):
    return int(value) if value == int(value) else float(value)


def interval(row):
    return instant(row["start_at"]), instant(row["end_at"])


def overlaps(first, second):
    return first[0] < second[1] and second[0] < first[1]


def merged(rows):
    return union((a, b) for a, b in rows if a < b)


def contained(span, windows):
    return span[0] >= span[1] or any(
        start <= span[0] and span[1] <= end for start, end in merged(windows)
    )


def shift_clock(anchor, amount, clock, calendars, calendar_ref=None, direction="forward"):
    """Count elapsed or declared operating minutes, preserving unknown horizons."""
    if amount is None or amount < 0:
        return None
    sign = 1 if direction == "forward" else -1
    if clock == "elapsed_minutes":
        return anchor + timedelta(minutes=sign * amount)
    if clock != "operating_minutes" or calendar_ref not in calendars:
        return None
    if calendars[calendar_ref].get("coverage", "complete") != "complete":
        return None
    if amount == 0:
        return anchor
    windows = merged([interval(row) for row in calendars[calendar_ref]["windows"]])
    if sign < 0:
        windows.reverse()
    remaining = amount
    for start, end in windows:
        if sign > 0:
            cursor = max(start, anchor)
            available = max(0, minutes(cursor, end))
            if remaining <= available:
                return cursor + timedelta(minutes=remaining)
        else:
            cursor = min(end, anchor)
            available = max(0, minutes(start, cursor))
            if remaining <= available:
                return cursor - timedelta(minutes=remaining)
        remaining -= available
    return None


def validate_process(process):
    errors, unknowns = set(), set()
    steps = {row["id"]: row for row in process["steps"]}
    if len(steps) != len(process["steps"]):
        errors.add("duplicate_step_id")
    for step in steps.values():
        duration = step["run_duration"]
        low, high = duration["minimum_minutes"], duration["maximum_minutes"]
        if low is None or high is None:
            unknowns.add("duration:" + step["id"])
        elif low < 0 or high < low:
            errors.add("invalid_duration")
        if duration["clock"] != "elapsed_minutes":
            errors.add("unsupported_run_clock")
        if step["setup_minutes"] < 0 or step["cleanup_minutes"] < 0:
            errors.add("invalid_setup_cleanup")
        if step["mode"] not in {"active", "unattended"}:
            errors.add("invalid_step_mode")
        requirement = step.get("resource_requirement")
        if requirement:
            if quantity(requirement["quantity"]) <= 0 or not requirement["unit"]:
                errors.add("invalid_resource_requirement")
            if step["occupancy_policy"] == "unknown":
                unknowns.add("occupancy:" + step["id"])
    if any(s["step_id"] not in steps for s in process["supplies"]):
        errors.add("unknown_supply_step")
    edges = defaultdict(list)
    for edge in process["dependencies"]:
        if edge["from_step"] not in steps or edge["to_step"] not in steps:
            errors.add("unknown_prerequisite")
        else:
            edges[edge["from_step"]].append(edge["to_step"])

        minimum, maximum = edge["minimum_lag_minutes"], edge["maximum_lag_minutes"]
        if minimum is None:
            unknowns.add("lag:" + edge["from_step"] + "/" + edge["to_step"])
        elif minimum < 0 or (maximum is not None and maximum < minimum):
            errors.add("invalid_lag_range")
    visited, active = set(), set()

    def visit(identifier):
        if identifier in active:
            errors.add("cyclic_dependencies")
            return
        if identifier in visited:
            return
        active.add(identifier)
        for successor in edges[identifier]:
            visit(successor)
        active.remove(identifier)
        visited.add(identifier)

    for identifier in steps:
        visit(identifier)
    return {"errors": sorted(errors), "unknowns": sorted(unknowns)}


def churn(base, blocks):
    old = {row["id"]: row for row in base}
    new = {row["id"]: row for row in blocks}
    changed, displacement, duration_change = set(old) - set(new), 0, 0
    for identifier in old.keys() & new.keys():
        old_span, new_span = interval(old[identifier]), interval(new[identifier])
        if old_span != new_span or old[identifier]["episode_id"] != new[identifier]["episode_id"]:
            changed.add(identifier)
        displacement += abs(minutes(old_span[0], new_span[0]))
        duration_change += abs(minutes(*old_span) - minutes(*new_span))
    return {
        "changed_existing_block_count": len(changed),
        "absolute_start_displacement_minutes": displacement,
        "absolute_duration_change_minutes": duration_change,
        "added_count": len(set(new) - set(old)),
        "removed_count": len(set(old) - set(new)),
    }


def candidate_key(result):
    change = result["churn"]
    return (
        bool(result.get("hard_unknowns")),
        tuple(result["prioritized_unmet_vector"]),
        change["changed_existing_block_count"],
        change["absolute_start_displacement_minutes"],
        change["absolute_duration_change_minutes"],
        result["id"],
    )


def capacity_at(resource, timestamp):
    for row in resource.get("capacity_intervals", []):
        start, end = interval(row)
        if start <= timestamp < end:
            return quantity(row["quantity"])
    default = resource["capacity"]["quantity"]
    return None if default is None else quantity(default)


def check_candidate(candidate, packet, process, resources, calendars, policy):
    now, deadline = instant(packet["planning_boundary"]), instant(packet["deadline_at"])
    errors, unknowns = set(), set()
    blocks, occupancies, bounds = [], [], defaultdict(list)
    booking_support = {}
    steps = {row["id"]: row for row in process["steps"] if row["scope_state"] == "current"}
    used_minutes, counts = defaultdict(int), defaultdict(int)
    passive_minutes = 0
    for row in candidate["placements"]:
        if row["step_id"] not in steps:
            errors.add("ineligible_step")
            continue
        step = steps[row["step_id"]]
        if row["episode_id"] != step["episode_id"]:
            errors.add("episode_mismatch")
        selected = step["run_duration"][policy["duration_selector"]]
        duration = row["run_minutes"] if row.get("run_minutes") is not None else selected
        if duration is None:
            unknowns.add("duration:" + step["id"])
            continue
        if duration < 0:
            errors.add("invalid_duration")
            continue
        if not step["divisible"] and duration != selected:
            errors.add("indivisible_duration")
        start = instant(row["start_at"])
        run_start = start + timedelta(minutes=step["setup_minutes"])
        run_end = run_start + timedelta(minutes=duration)
        cleanup_end = run_end + timedelta(minutes=step["cleanup_minutes"])
        end = cleanup_end + timedelta(minutes=step.get("turnaround_minutes", 0))
        passive_minutes += step.get("turnaround_minutes", 0)
        if start < now:
            existing_started = any(
                old["id"].rsplit("/", 1)[0] == row["placement_id"]
                and old["step_id"] == row["step_id"]
                and old["episode_id"] == row["episode_id"]
                and interval(old)[0] <= now < interval(old)[1]
                for old in packet["base_blocks"]
            )
            supported_started = row["placement_id"] in packet.get(
                "supported_started_placement_ids", []
            )
            if end <= now or not (existing_started or supported_started):
                errors.add("unsupported_past_placement")
        bounds[step["id"]].append(
            dict(start=start, run_start=run_start, run_end=run_end, finish=end)
        )
        used_minutes[step["id"]] += duration
        counts[step["id"]] += 1
        phases = [("setup", start, run_start), ("cleanup", run_end, cleanup_end)]
        if step["mode"] == "active":
            phases.append(("active", run_start, run_end))
        else:
            passive_minutes += duration
        attended = [
            (phase_start, phase_end)
            for _, phase_start, phase_end in phases
            if phase_end > phase_start
        ]
        for phase, phase_start, phase_end in phases:
            if phase_end <= phase_start:
                continue
            blocks.append(
                {
                    "id": row["placement_id"] + "/" + phase,
                    "placement_id": row["placement_id"],
                    "step_id": step["id"],
                    "episode_id": row["episode_id"],
                    "start_at": phase_start.isoformat(),
                    "end_at": phase_end.isoformat(),
                }
            )
        if end > deadline:
            errors.add("deadline")
        requirement = step.get("resource_requirement")
        if not requirement:
            if row.get("resource_id"):
                errors.add("unexpected_resource")
            continue
        resource = resources.get(row["resource_id"])
        if resource is None:
            errors.add("unknown_resource")
            continue
        if (
            resource["id"] not in requirement["resource_ids"]
            or resource["capability"] != requirement["capability"]
        ):
            errors.add("incompatible_resource")
        if not resource["capacity"]["unit"]:
            unknowns.add("capacity:" + resource["id"])
        elif resource["capacity"]["unit"] != requirement["unit"]:
            errors.add("unit_mismatch")
        if step["occupancy_policy"] == "unknown":
            unknowns.add("occupancy:" + step["id"])
        for key, spans in [
            ("occupancy_calendar_ref", [(start, end)]),
            ("run_calendar_ref", [(run_start, run_end)]),
            ("access_calendar_ref", attended),
        ]:
            reference = resource.get(key)
            if reference not in calendars:
                unknowns.add(key + ":" + resource["id"])
                continue
            windows = [interval(value) for value in calendars[reference]["windows"]]
            if calendars[reference].get("coverage", "complete") != "complete":
                unknowns.add(key + ":" + resource["id"])
                continue
            if any(not contained(span, windows) for span in spans):
                errors.add("outside_" + key.removesuffix("_ref"))
        if any(
            overlaps((max(now, start), end), interval(value)) for value in resource["unavailable"]
        ):
            errors.add("resource_unavailable")
        matching = [
            value
            for value in resource["reservations"]
            if value["id"] == row.get("booking_id") and value["owner_step_id"] == step["id"]
        ]
        support = "observed_available"
        covered_booking_id = None
        if matching:
            booking = matching[0]
            support = booking["status"]
            quantity_ok = (
                quantity(booking["quantity"]) >= quantity(requirement["quantity"])
                and booking["unit"] == requirement["unit"]
            )
            if (
                support == "confirmed"
                and quantity_ok
                and contained((start, end), [interval(booking)])
            ):
                covered_booking_id = booking["id"]
            elif support == "confirmed":
                errors.add("booking_scope_mismatch")
                support = "scope_mismatch"
        booking_support[step["id"]] = support
        if requirement["booking_required"] and support != "confirmed":
            unknowns.add("booking:" + step["id"])
        occupancies.append(
            {
                "step_id": step["id"],
                "placement_id": row["placement_id"],
                "episode_id": step["episode_id"],
                "resource_id": resource["id"],
                "unit": requirement["unit"],
                "quantity": requirement["quantity"],
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "covered_booking_id": covered_booking_id,
            }
        )
    for step_id, step in steps.items():
        selected = step["run_duration"][policy["duration_selector"]]
        overhead = (
            step["setup_minutes"] + step["cleanup_minutes"] + step.get("turnaround_minutes", 0)
        )
        if used_minutes[step_id] != selected or (overhead and not counts[step_id]):
            errors.add("incomplete_step")
        if not step["divisible"] and counts[step_id] > 1:
            errors.add("indivisible_split")
    # Once-per-window student buffering is applied before merging supplied windows.
    buffer_minutes = packet["buffer_minutes"]
    student_windows = [
        (start, end - timedelta(minutes=buffer_minutes))
        for start, end in map(interval, packet["student_windows"])
    ]
    future = []
    for row in blocks:
        start, end = interval(row)
        span = (max(now, start), end)
        if span[0] >= span[1]:
            continue
        future.append((span, row["placement_id"]))
        if not contained(span, student_windows):
            errors.add("student_unavailable")
        if any(overlaps(span, interval(busy)) for busy in packet["busy"]):
            errors.add("student_busy")
    for index, (span, placement_id) in enumerate(future):
        for other, other_id in future[index + 1 :]:
            if overlaps(span, other):
                errors.add("student_overlap")
            if placement_id != other_id and packet["break_minutes"]:
                first, second = sorted([span, other])
                if 0 <= minutes(first[1], second[0]) < packet["break_minutes"]:
                    errors.add("interblock_break")
    protected = [
        row
        for row in packet["base_blocks"]
        if row.get("protected") or interval(row)[0] < now < interval(row)[1]
    ]
    current_blocks = {row["id"]: row for row in blocks}
    for old in packet["base_blocks"]:
        current = current_blocks.get(old["id"])
        if current and (
            old["episode_id"] != current["episode_id"] or old["step_id"] != current["step_id"]
        ):
            errors.add("block_identity_rebound")
    for old in protected:
        current = current_blocks.get(old["id"])
        if (
            current is None
            or interval(old) != interval(current)
            or old["episode_id"] != current["episode_id"]
        ):
            errors.add("protected_block_changed")
    for resource_id, resource in resources.items():
        if not any(row["resource_id"] == resource_id for row in occupancies):
            continue
        events = defaultdict(Decimal)
        population = [
            row
            for row in occupancies
            if row["resource_id"] == resource_id and row["covered_booking_id"] is None
        ]
        for booking in resource["reservations"]:
            if booking["status"] == "confirmed":
                if booking["unit"] != resource["capacity"]["unit"]:
                    errors.add("reservation_unit_mismatch")
                population.append(booking)
                claims = defaultdict(Decimal)
                for claim in occupancies:
                    if (
                        claim["resource_id"] == resource_id
                        and claim["covered_booking_id"] == booking["id"]
                    ):
                        left, right = interval(claim)
                        claims[left] += quantity(claim["quantity"])
                        claims[right] -= quantity(claim["quantity"])
                claimed = Decimal(0)
                for timestamp in sorted(claims):
                    claimed += claims[timestamp]
                    if claimed > quantity(booking["quantity"]):
                        errors.add("booking_capacity")
        for row in population:
            start, end = interval(row)
            start = max(now, start)
            if end <= start:
                continue
            events[start] += quantity(row["quantity"])
            events[end] -= quantity(row["quantity"])
        for row in resource.get("capacity_intervals", []):
            for stamp in interval(row):
                events.setdefault(stamp, Decimal(0))
        required = merged(
            [interval(row) for row in occupancies if row["resource_id"] == resource_id]
        )
        for left, right in required:
            events.setdefault(max(left, now), Decimal(0))
            events.setdefault(right, Decimal(0))
        occupied = Decimal(0)
        for timestamp in sorted(events):
            occupied += events[timestamp]
            if timestamp < now or not any(left <= timestamp < right for left, right in required):
                continue
            cap = capacity_at(resource, timestamp)
            if cap is None:
                unknowns.add("capacity:" + resource_id)
            elif occupied > cap:
                errors.add("resource_capacity")
    wait_minutes = 0
    for edge in process["dependencies"]:
        if not bounds[edge["from_step"]] or not bounds[edge["to_step"]]:
            errors.add("missing_dependency_placement")
            continue
        before = max(b[edge["from_anchor"]] for b in bounds[edge["from_step"]])
        after = min(b[edge["to_anchor"]] for b in bounds[edge["to_step"]])
        minimum = shift_clock(
            before, edge["minimum_lag_minutes"], edge["clock"], calendars, edge["calendar_ref"]
        )
        if minimum is None:
            unknowns.add("dependency_clock")
        elif after < minimum:
            errors.add("minimum_lag")
        if edge["maximum_lag_minutes"] is not None:
            maximum = shift_clock(
                before, edge["maximum_lag_minutes"], edge["clock"], calendars, edge["calendar_ref"]
            )
            if maximum is None:
                unknowns.add("dependency_clock")
            elif after > maximum or (after == maximum and not edge["maximum_inclusive"]):
                errors.add("maximum_lag")
        wait_minutes += max(0, minutes(before, after))
    for supply in process["supplies"]:
        if supply.get("required_quantity") is not None:
            if not supply.get("unit") or supply.get("available_quantity") is None:
                unknowns.add("supply_quantity:" + supply["id"])
            elif quantity(supply["required_quantity"]) > quantity(supply["available_quantity"]):
                errors.add("supply_quantity_shortfall")
        if not supply["source_available"] or supply["ready_at"] is None:
            unknowns.add("supply:" + supply["id"])
        elif bounds[supply["step_id"]] and min(
            b["start"] for b in bounds[supply["step_id"]]
        ) < instant(supply["ready_at"]):
            errors.add("supply_not_ready")
    resource_minutes, future_resource_minutes = defaultdict(Decimal), defaultdict(Decimal)
    for row in occupancies:
        start, end = interval(row)
        key = row["resource_id"] + "|" + row["unit"]
        resource_minutes[key] += quantity(row["quantity"]) * quantity(minutes(start, end))
        future_resource_minutes[key] += quantity(row["quantity"]) * quantity(
            max(0, minutes(max(start, now), end))
        )
    active_minutes = sum(minutes(*span) for span, _ in future)
    demand_mapping = reconcile_active_demand(
        process.get("active_demand_mapping"), active_minutes, set(steps)
    )
    if demand_mapping and demand_mapping["state"] == "unresolved":
        unknowns.add("active_demand_mapping")
    return {
        "id": candidate["id"],
        "violations": sorted(errors),
        "unknowns": sorted(unknowns),
        "hard_unknowns": sorted(value for value in unknowns if not value.startswith("booking:")),
        "active_minutes": active_minutes,
        "active_demand_mapping": demand_mapping,
        "full_active_minutes": sum(minutes(*interval(row)) for row in blocks),
        "passive_elapsed_minutes": passive_minutes,
        "dependency_wait_minutes": wait_minutes,
        "resource_quantity_minutes": {
            key: number(value) for key, value in resource_minutes.items()
        },
        "future_resource_quantity_minutes": {
            key: number(value) for key, value in future_resource_minutes.items()
        },
        "blocks": sorted(blocks, key=lambda row: row["id"]),
        "occupancies": occupancies,
        "booking_support": booking_support,
        "protected_block_ids": sorted(row["id"] for row in protected),
        "churn": churn(packet["base_blocks"], blocks),
        "prioritized_unmet_vector": [0],
        "actual_observations_created": 0,
    }


def reconcile_active_demand(mapping, phase_active_minutes, step_ids):
    if mapping is None:
        return None
    applicable = set(mapping["phase_scope_refs"]) == step_ids and bool(
        mapping["active_demand_scope_id"]
    )
    matched = (
        applicable
        and mapping["basis"] == "phase_partition"
        and mapping["parent_remaining_minutes"] == phase_active_minutes
    )
    overridden = (
        applicable
        and mapping["basis"] == "explicit_phase_override"
        and mapping.get("override_minutes") == phase_active_minutes
        and bool(mapping.get("override_ref"))
    )
    state = "partition_matched" if matched else ("scoped_override" if overridden else "unresolved")
    return {
        "state": state,
        "active_demand_scope_id": mapping["active_demand_scope_id"],
        "phase_active_minutes": phase_active_minutes,
        "combined_remaining_minutes": phase_active_minutes if matched or overridden else None,
        "parent_additional_minutes": 0 if matched or overridden else None,
    }


def capacity_proof(certificate, process, resources, calendars, policy, packet=None):
    if not certificate:
        return None
    resource = resources[certificate["resource_id"]]
    steps = {row["id"]: row for row in process["steps"]}
    demand = Decimal(0)
    valid = certificate["unit"] == resource["capacity"]["unit"] and len(
        set(certificate["step_ids"])
    ) == len(certificate["step_ids"])
    for identifier in certificate["step_ids"]:
        step = steps[identifier]
        requirement = step["resource_requirement"]
        valid &= (
            step["scope_state"] == "current"
            and requirement["resource_ids"] == [resource["id"]]
            and requirement["unit"] == certificate["unit"]
        )
        if packet:
            now = instant(packet["planning_boundary"])
            started_block = any(
                row["step_id"] == identifier and interval(row)[0] < now < interval(row)[1]
                for row in packet["base_blocks"]
            )
            started_placement = any(
                row["step_id"] == identifier
                and row["placement_id"] in packet.get("supported_started_placement_ids", [])
                for candidate in packet["candidates"]
                for row in candidate["placements"]
            )
            if started_block or started_placement:
                valid = False
        duration = step["run_duration"][policy["duration_selector"]]
        if duration is None or step["occupancy_policy"] != "continuous":
            valid = False
            continue
        demand += quantity(requirement["quantity"]) * (
            duration
            + step["setup_minutes"]
            + step["cleanup_minutes"]
            + step.get("turnaround_minutes", 0)
        )
    start, end = interval(certificate["window"])
    windows = [interval(row) for row in calendars[resource["occupancy_calendar_ref"]]["windows"]]
    if packet:
        now, deadline = instant(packet["planning_boundary"]), instant(packet["deadline_at"])
        eligible = [
            (max(now, left), min(deadline, right))
            for left, right in windows
            if max(now, left) < min(deadline, right)
        ]
        valid &= all(contained(span, [(start, end)]) for span in eligible)
    capacity = Decimal(0)
    changes = {stamp for row in resource.get("capacity_intervals", []) for stamp in interval(row)}
    for left, right in merged(windows):
        a, b = max(start, left), min(end, right)
        if a >= b:
            continue
        points = sorted({a, b} | {stamp for stamp in changes if a < stamp < b})
        for x, y in zip(points, points[1:], strict=False):
            cap = capacity_at(resource, x)
            if cap is None:
                valid = False
            else:
                capacity += quantity(minutes(x, y)) * cap
    # This whole-process proof applies to future, unstarted demand. A started
    # process requires an explicitly scoped future-remainder certificate.
    valid &= calendars[resource["occupancy_calendar_ref"]].get("coverage", "complete") == "complete"
    return {
        "valid": bool(valid),
        "resource_id": resource["id"],
        "unit": certificate["unit"],
        "required_quantity_minutes": number(demand),
        "available_quantity_minutes": number(capacity),
        "shortfall_quantity_minutes": number(max(0, demand - capacity)),
    }


def latest_start(certificate, packet, process, evaluated, policy):
    if not certificate:
        return {"status": "unresolved", "at": None, "proof_scope": "bounded candidate set"}
    if certificate["kind"] != "serial_elapsed_chain":
        return {"status": "unresolved", "at": None, "proof_scope": "unsupported certificate"}
    chain = certificate["step_ids"]
    steps = {row["id"]: row for row in process["steps"]}
    edges = {(row["from_step"], row["to_step"]): row for row in process["dependencies"]}
    if set(chain) != set(steps) or len(chain) != len(steps) or len(edges) != len(chain) - 1:
        return {"status": "unresolved", "at": None, "proof_scope": "chain scope mismatch"}
    total = sum(
        steps[name]["run_duration"][policy["duration_selector"]]
        + steps[name]["setup_minutes"]
        + steps[name]["cleanup_minutes"]
        + steps[name].get("turnaround_minutes", 0)
        for name in chain
    )
    for before, after in zip(chain, chain[1:], strict=False):
        edge = edges.get((before, after))
        if (
            edge is None
            or edge["clock"] != "elapsed_minutes"
            or edge["from_anchor"] != "finish"
            or edge["to_anchor"] != "start"
        ):
            return {"status": "unresolved", "at": None, "proof_scope": "unsupported clock or chain"}
        total += edge["minimum_lag_minutes"]
    bound = instant(packet["deadline_at"]) - timedelta(minutes=total)
    witness = evaluated.get(certificate["witness_candidate_id"])
    supplied = next(
        (row for row in packet["candidates"] if row["id"] == certificate["witness_candidate_id"]),
        None,
    )
    first = (
        [row for row in supplied["placements"] if row["step_id"] == chain[0]] if supplied else []
    )
    proven = (
        witness
        and not witness["violations"]
        and not witness["unknowns"]
        and len(first) == 1
        and instant(first[0]["start_at"]) == bound
    )
    if not proven:
        return {
            "status": "unresolved",
            "at": None,
            "candidate_upper_bound": bound.isoformat(),
            "proof_scope": "boundary witness failed forward constraints",
        }
    return {
        "status": "certified",
        "at": bound.isoformat(),
        "chain_elapsed_minutes": total,
        "proof_scope": "fixed serial elapsed chain with forward-valid boundary witness",
    }


def evaluate_schedule(packet, process, resource_data, policy):
    validation = validate_process(process)
    if validation["errors"] or validation["unknowns"]:
        return {
            "status": "invalid_inputs" if validation["errors"] else "unknown_inputs",
            "input_validation": validation,
            "selected_candidate_id": None,
        }
    resources = {row["id"]: row for row in resource_data["resources"]}
    calendars = {
        row["id"]: row for row in resource_data["calendars"] + packet.get("calendar_additions", [])
    }

    evaluated = {
        row["id"]: check_candidate(row, packet, process, resources, calendars, policy)
        for row in packet["candidates"]
    }
    eligible = [row for row in evaluated.values() if not row["violations"]]
    proof = capacity_proof(
        packet.get("capacity_certificate"), process, resources, calendars, policy, packet
    )
    common = {
        "candidate_count": len(evaluated),
        "capacity_certificate": proof,
        "rejected_candidates": {
            key: row["violations"] for key, row in evaluated.items() if row["violations"]
        },
        "historical_episode_ids": [row["episode_id"] for row in process["historical_episodes"]],
        "latest_start": latest_start(
            packet.get("latest_start_certificate"), packet, process, evaluated, policy
        ),
    }
    if not eligible:
        protected = any(
            "protected_block_changed" in row["violations"] for row in evaluated.values()
        )
        status = "protected_conflict" if protected else "no_feasible_schedule_found"
        if proof and proof["valid"] and proof["shortfall_quantity_minutes"] > 0:
            status = "infeasible"
        return {**common, "status": status, "selected_candidate_id": None}
    selected = min(eligible, key=candidate_key)
    return {
        **common,
        **selected,
        "status": "provisional" if selected["unknowns"] else "feasible",
        "selected_candidate_id": selected["id"],
    }


POLICY = {"duration_selector": "maximum_minutes", "lead_time_selector": "maximum_minutes"}


def lead_bounds(lead, calendars):
    result = dict(
        state="unknown",
        earliest_ready_at=None,
        latest_ready_at=None,
        latest_trigger_at=None,
        selected_minutes=None,
    )
    low, high = lead.minimum_minutes, lead.maximum_minutes
    if not lead.source_available or low is None or high is None or low > high:
        return result
    values = [
        shift_clock(anchor, amount, lead.clock, calendars, lead.calendar_ref, direction)
        for anchor, amount, direction in (
            (lead.anchor, low, "forward"),
            (lead.anchor, high, "forward"),
            (lead.deadline, high, "backward"),
        )
    ]
    if all(values):
        result.update(
            state="known_range",
            earliest_ready_at=values[0].isoformat(),
            latest_ready_at=values[1].isoformat(),
            latest_trigger_at=values[2].isoformat(),
            selected_minutes=high,
        )
    return result


def propose_candidates(packet, process, resources, calendars):
    """Bounded chronological search over calendar, release, booking and phase boundaries."""
    steps = {s["id"]: s for s in process["steps"] if s["scope_state"] == "current"}
    now, deadline = instant(packet["planning_boundary"]), instant(packet["deadline_at"])
    needed = {
        rid
        for step in steps.values()
        for rid in (step.get("resource_requirement") or {}).get("resource_ids", [])
    }
    resources = {rid: resources[rid] for rid in needed if rid in resources}
    calendar_ids = {
        r[key]
        for r in resources.values()
        for key in ("access_calendar_ref", "run_calendar_ref", "occupancy_calendar_ref")
    }
    calendar_ids.update(e["calendar_ref"] for e in process["dependencies"])
    pivots = {now, deadline}
    for span in [
        *packet["student_windows"],
        *packet["busy"],
        *packet["base_blocks"],
        *(w for key in calendar_ids if key in calendars for w in calendars[key]["windows"]),
        *(
            w
            for r in resources.values()
            for w in [*r["unavailable"], *r["reservations"], *r.get("capacity_intervals", [])]
        ),
    ]:
        pivots.update(interval(span))
    pivots.update(instant(s["ready_at"]) for s in process["supplies"] if s["ready_at"])
    edges = process["dependencies"]
    ordered = []
    while len(ordered) < len(steps):
        ready = [
            s
            for s in steps
            if s not in ordered
            and all(e["from_step"] in ordered for e in edges if e["to_step"] == s)
        ]
        if not ready:
            break
        ordered.append(min(ready, key=lambda s: (steps[s]["priority"], s)))
    candidates = []
    attempts = 0

    def walk(placements, times):
        nonlocal attempts
        if len(placements) == len(ordered):
            candidates.append(dict(id=f"generated-{len(candidates):03}", placements=placements))
            return
        name = ordered[len(placements)]
        step = steps[name]
        run = step["run_duration"]["maximum_minutes"]
        if run is None:
            return
        total = (
            step["setup_minutes"]
            + run
            + step["cleanup_minutes"]
            + step.get("turnaround_minutes", 0)
        )
        offsets = dict(
            start=0,
            run_start=step["setup_minutes"],
            run_end=step["setup_minutes"] + run,
            finish=total,
        )
        starts = {p - timedelta(minutes=offset) for p in pivots for offset in offsets.values()}
        starts.update(
            t["finish"] + timedelta(minutes=packet["break_minutes"]) for t in times.values()
        )
        for edge in edges:
            if edge["to_step"] != name or edge["from_step"] not in times:
                continue
            for lag in ("minimum_lag_minutes", "maximum_lag_minutes"):
                at = shift_clock(
                    times[edge["from_step"]][edge["from_anchor"]],
                    edge[lag],
                    edge["clock"],
                    calendars,
                    edge["calendar_ref"],
                )
                if at:
                    starts.add(at - timedelta(minutes=offsets[edge["to_anchor"]]))
        old = next(
            (
                b
                for b in packet["base_blocks"]
                if b["step_id"] == name and b["episode_id"] == step["episode_id"]
            ),
            None,
        )
        pid = old["id"].rsplit("/", 1)[0] if old else name
        if not old and any(
            b["step_id"] == name and b["episode_id"] != step["episode_id"]
            for b in packet["base_blocks"]
        ):
            pid = name + "-" + fingerprint([step["work_lineage_id"], step["episode_id"]])[:12]
        if old:
            phase = old["id"].rsplit("/", 1)[-1]
            old_start = instant(old["start_at"]) - timedelta(
                minutes={
                    "setup": 0,
                    "active": offsets["run_start"],
                    "cleanup": offsets["run_end"],
                }.get(phase, 0)
            )
            starts.add(old_start)
        else:
            old_start = None
        requirement = step.get("resource_requirement")
        confirmed_starts = {
            instant(b["start_at"])
            for r in resources.values()
            for b in r["reservations"]
            if b["owner_step_id"] == name and b["status"] == "confirmed"
        }
        for start in sorted(starts, key=lambda s: (s != old_start, s not in confirmed_starts, s)):
            if start < now and start != old_start or start + timedelta(minutes=total) > deadline:
                continue
            for rid in requirement["resource_ids"] if requirement else [None]:
                if attempts >= 350 or len(candidates) >= 12:
                    return
                attempts += 1
                bookings = resources.get(rid, {}).get("reservations", [])
                booking = next(
                    (
                        b["id"]
                        for b in bookings
                        if b["owner_step_id"] == name
                        and b["status"] == "confirmed"
                        and contained((start, start + timedelta(minutes=total)), [interval(b)])
                    ),
                    None,
                )
                row = dict(
                    placement_id=pid,
                    episode_id=step["episode_id"],
                    step_id=name,
                    start_at=start.isoformat(),
                    resource_id=rid,
                    booking_id=booking,
                )
                chosen = placements + [row]
                current = {p["step_id"] for p in chosen}
                partial = process | dict(
                    steps=[s for s in steps.values() if s["id"] in current],
                    dependencies=[e for e in edges if {e["from_step"], e["to_step"]} <= current],
                    supplies=[s for s in process["supplies"] if s["step_id"] in current],
                    active_demand_mapping=None,
                )
                result = check_candidate(
                    dict(id="search", placements=chosen),
                    packet
                    | dict(
                        base_blocks=[b for b in packet["base_blocks"] if b["step_id"] in current]
                    ),
                    partial,
                    resources,
                    calendars,
                    POLICY,
                )
                if not result["violations"]:
                    walk(
                        chosen,
                        times
                        | {name: {k: start + timedelta(minutes=v) for k, v in offsets.items()}},
                    )

    if len(ordered) == len(steps):
        walk([], {})
    return candidates


def partial_service(packet, proc, resources, calendars):
    """Retain a forward-valid subset on a bounded unsuccessful complete search."""
    eligible = {s["id"]: s for s in proc["steps"] if s["scope_state"] == "current"}
    ordered = sorted(eligible, key=lambda k: (eligible[k]["priority"], k))
    accepted = set()
    chosen = None
    # Lower-priority prerequisites may be necessary to serve a higher-priority step.
    for key in ordered[:12]:
        if key in accepted:
            continue
        required = accepted | {key}
        while True:
            expanded = required | {
                e["from_step"] for e in proc["dependencies"] if e["to_step"] in required
            }
            if expanded == required:
                break
            required = expanded
        if not required <= eligible.keys():
            continue
        sub = proc | dict(
            steps=[eligible[k] for k in ordered if k in required],
            dependencies=[e for e in proc["dependencies"] if e["to_step"] in required],
            supplies=[s for s in proc["supplies"] if s["step_id"] in required],
            active_demand_mapping=None,
        )
        preserve = [
            b
            for b in packet["base_blocks"]
            if b["step_id"] not in required
            and (
                b.get("protected") or instant(b["start_at"]) < instant(packet["planning_boundary"])
            )
        ]
        scoped = packet | dict(
            base_blocks=[b for b in packet["base_blocks"] if b["step_id"] in required],
            busy=packet["busy"]
            + [dict(start_at=b["start_at"], end_at=b["end_at"]) for b in preserve],
        )
        candidates = propose_candidates(scoped, sub, resources, calendars)
        checks = [check_candidate(c, scoped, sub, resources, calendars, POLICY) for c in candidates]
        valid = [c for c in checks if not c["violations"] and not c["hard_unknowns"]]
        if valid:
            chosen = min(valid, key=candidate_key)
            accepted = required
    return dict(
        served_step_ids=sorted(accepted),
        unmet_step_ids=[k for k in ordered if k not in accepted],
        prioritized_unmet_vector=[
            0 if k in accepted else eligible[k]["run_duration"]["maximum_minutes"] for k in ordered
        ],
        blocks=chosen["blocks"] if chosen else [],
        active_minutes=chosen["active_minutes"] if chosen else 0,
    )


def plan(process: Process, inventory: Inventory, schedule: Schedule, *, generate=True):
    proc = process.model_dump(mode="json")
    packet = schedule.model_dump(mode="json")
    catalog = inventory.model_dump(mode="json")
    resources = {r["id"]: r for r in catalog["resources"]}
    calendars = {c["id"]: c for c in catalog["calendars"]}
    aliases = {alias: r["id"] for r in resources.values() for alias in r["aliases"]}
    for step in proc["steps"]:
        requirement = step.get("resource_requirement")
        if requirement:
            requirement["resource_ids"] = list(
                dict.fromkeys(aliases.get(r, r) for r in requirement["resource_ids"])
            )
    for c in packet["candidates"]:
        for p in c["placements"]:
            p["resource_id"] = aliases.get(p["resource_id"], p["resource_id"])
    validation = validate_process(proc)
    leads = {}
    for s in process.supplies:
        if s.lead:
            leads[s.id] = lead_bounds(s.lead, calendars)
            target = next(row for row in proc["supplies"] if row["id"] == s.id)
            if target["ready_at"] is None:
                target["ready_at"] = leads[s.id]["latest_ready_at"]
            else:
                leads[s.id]["observed_ready_at"] = target["ready_at"]
    if validation["unknowns"] and not validation["errors"]:
        blocked = {
            step["id"]
            for step in proc["steps"]
            if step["run_duration"]["maximum_minutes"] is None
            or step["run_duration"]["minimum_minutes"] is None
            or step["occupancy_policy"] == "unknown"
        }
        blocked.update(
            e["to_step"] for e in proc["dependencies"] if e["minimum_lag_minutes"] is None
        )
        while True:
            closed = blocked | {
                e["to_step"] for e in proc["dependencies"] if e["from_step"] in blocked
            }
            if closed == blocked:
                break
            blocked = closed
        known = {s["id"] for s in proc["steps"]} - blocked
        if known:
            sub = process.model_copy(
                update=dict(
                    steps=tuple(s for s in process.steps if s.id in known),
                    dependencies=tuple(
                        e
                        for e in process.dependencies
                        if e.from_step in known and e.to_step in known
                    ),
                    supplies=tuple(s for s in process.supplies if s.step_id in known),
                    active_demand_mapping=None,
                )
            )
            # Keep unresolved commitments occupied while evaluating only independent work.
            reserved = tuple(
                Span(start_at=b.start_at, end_at=b.end_at)
                for b in schedule.base_blocks
                if b.step_id not in known
            )
            scoped = schedule.model_copy(
                update=dict(
                    busy=(*schedule.busy, *reserved),
                    base_blocks=tuple(b for b in schedule.base_blocks if b.step_id in known),
                    candidates=tuple(
                        c.model_copy(
                            update=dict(
                                placements=tuple(p for p in c.placements if p.step_id in known)
                            )
                        )
                        for c in schedule.candidates
                    ),
                )
            )
            partial = plan(sub, inventory, scoped, generate=generate)
            return dict(
                status="unknown_inputs",
                input_validation=validation,
                blocked_step_ids=sorted(blocked),
                known_steps_plan=partial,
                selected_candidate_id=None,
                lead_times=leads,
                actual_observations_created=0,
            )
    if generate and not validation["errors"] and not validation["unknowns"]:
        existing = {c["id"] for c in packet["candidates"]}
        packet["candidates"].extend(
            c
            for c in propose_candidates(packet, proc, resources, calendars)
            if c["id"] not in existing
        )
    # Derive proof candidates from the actual requested work and physical inventory.
    proofs = []
    if not validation["errors"] and not validation["unknowns"]:
        for r in resources.values():
            ids = [
                s["id"]
                for s in proc["steps"]
                if s.get("resource_requirement")
                and s["resource_requirement"]["resource_ids"] == [r["id"]]
            ]
            if (
                ids
                and r["capacity"]["quantity"] is not None
                and r["capacity"]["unit"]
                and r["occupancy_calendar_ref"] in calendars
            ):
                cert = dict(
                    resource_id=r["id"],
                    step_ids=ids,
                    unit=r["capacity"]["unit"],
                    window=dict(start_at=packet["planning_boundary"], end_at=packet["deadline_at"]),
                )
                proof = capacity_proof(cert, proc, resources, calendars, POLICY, packet)
                if proof["valid"] and proof["shortfall_quantity_minutes"] > 0:
                    proofs.append(cert)
    if proofs:
        packet["capacity_certificate"] = proofs[0]
    result = evaluate_schedule(packet, proc, catalog, POLICY)
    if generate and result["status"] in {
        "infeasible",
        "no_feasible_schedule_found",
        "protected_conflict",
    }:
        result["partial_service"] = partial_service(packet, proc, resources, calendars)
    selected = next(
        (c for c in packet["candidates"] if c["id"] == result.get("selected_candidate_id")), None
    )
    if selected:
        chain = sorted(selected["placements"], key=lambda p: instant(p["start_at"]))
        result["latest_start"] = latest_start(
            dict(
                kind="serial_elapsed_chain",
                step_ids=[p["step_id"] for p in chain],
                witness_candidate_id=selected["id"],
            ),
            packet,
            proc,
            {selected["id"]: result},
            POLICY,
        )
        proof = result["latest_start"]
        if generate and proof.get("candidate_upper_bound"):
            # Shift the selected serial chain to its necessary deadline bound and use
            # the ordinary forward checker, including resources, lags and protections.
            cursor = instant(proof["candidate_upper_bound"])
            by_step = {s.id: s for s in process.steps}
            minimum = {
                (e.from_step, e.to_step): e.minimum_lag_minutes for e in process.dependencies
            }
            witness = dict(id="latest-start-witness", placements=[])
            for i, p in enumerate(chain):
                step = by_step[p["step_id"]]
                if i:
                    cursor += timedelta(minutes=minimum[(chain[i - 1]["step_id"], step.id)])
                witness["placements"].append(p | dict(start_at=cursor.isoformat()))
                cursor += timedelta(
                    minutes=step.setup_minutes
                    + step.run_duration.maximum_minutes
                    + step.cleanup_minutes
                    + step.turnaround_minutes
                )
            checked = check_candidate(witness, packet, proc, resources, calendars, POLICY)
            result["latest_start"] = latest_start(
                dict(
                    kind="serial_elapsed_chain",
                    step_ids=[p["step_id"] for p in chain],
                    witness_candidate_id=witness["id"],
                ),
                packet | dict(candidates=[witness]),
                proc,
                {witness["id"]: checked},
                POLICY,
            )
        result["placements"] = selected["placements"]
    totals = {}
    for row in result.get("occupancies", []):
        key = (row["resource_id"], row["unit"])
        amount = quantity(row["quantity"])
        left, right = interval(row)
        full, future = totals.get(key, (Decimal(0), Decimal(0)))
        totals[key] = (
            full + amount * quantity(minutes(left, right)),
            future
            + amount * quantity(max(0, minutes(max(schedule.planning_boundary, left), right))),
        )
    result.update(
        resource_usage=[
            dict(
                resource_id=rid,
                unit=unit,
                quantity_minutes=number(full),
                future_quantity_minutes=number(future),
            )
            for (rid, unit), (full, future) in totals.items()
        ],
        lead_time_results=[dict(supply_id=k, **v) for k, v in leads.items()],
        candidate_rejections=[
            dict(candidate_id=k, reasons=v)
            for k, v in result.get("rejected_candidates", {}).items()
        ],
        lead_times=leads,
        search_scope="bounded_forward_candidates",
        buffer_policy="end_only_per_supplied_student_window",
    )
    return result

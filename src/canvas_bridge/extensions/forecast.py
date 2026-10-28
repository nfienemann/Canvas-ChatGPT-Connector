"""Standalone example module, built exclusively from the public numeric SDK."""

import json


def grade_forecast_manifest():
    def field(low, high):
        return {"type": "decimal", "minimum": str(low), "maximum": str(high)}

    def step(name, op, left, right):
        def operand(value):
            return {"constant": str(value)} if isinstance(value, int) else {"ref": value}

        return {"name": name, "op": op, "left": operand(left), "right": operand(right)}

    return json.dumps(
        {
            "sdk_version": "1.0.0",
            "module_id": "grade_forecast",
            "module_version": "1.0.0",
            "required_capabilities": ["get_grade_summary"],
            "permission_requirements": ["grade_planning"],
            "inputs": {
                "earned_points": field(0, 1000000),
                "possible_points": field("0.0001", 1000000),
                "future_possible_points": field(0, 1000000),
                "future_score_percent": field(0, 100),
            },
            "outputs": {
                "current_percent": field(0, 1000000),
                "forecast_percent": field(0, 1000000),
                "change_percentage_points": field(-1000000, 1000000),
            },
            "steps": [
                step("current_ratio", "divide", "earned_points", "possible_points"),
                step("current", "multiply", "current_ratio", 100),
                step("future_scaled", "multiply", "future_possible_points", "future_score_percent"),
                step("future_earned", "divide", "future_scaled", 100),
                step("total_earned", "add", "earned_points", "future_earned"),
                step("total_possible", "add", "possible_points", "future_possible_points"),
                step("forecast_ratio", "divide", "total_earned", "total_possible"),
                step("forecast", "multiply", "forecast_ratio", 100),
                step("change", "subtract", "forecast", "current"),
            ],
            "emit": {
                "current_percent": "current",
                "forecast_percent": "forecast",
                "change_percentage_points": "change",
            },
            "tests": [
                {
                    "inputs": {
                        "earned_points": "170",
                        "possible_points": "200",
                        "future_possible_points": "100",
                        "future_score_percent": "100",
                    },
                    "expected": {
                        "current_percent": "85",
                        "forecast_percent": "90",
                        "change_percentage_points": "5",
                    },
                },
                {
                    "inputs": {
                        "earned_points": "170",
                        "possible_points": "200",
                        "future_possible_points": "0",
                        "future_score_percent": "0",
                    },
                    "expected": {
                        "current_percent": "85",
                        "forecast_percent": "85",
                        "change_percentage_points": "0",
                    },
                },
                {
                    "inputs": {
                        "earned_points": "170",
                        "possible_points": "200",
                        "future_possible_points": "100",
                        "future_score_percent": "90",
                    },
                    "expected": {
                        "current_percent": "85",
                        "forecast_percent": "86.6667",
                        "change_percentage_points": "1.6667",
                    },
                },
            ],
        }
    ).encode()

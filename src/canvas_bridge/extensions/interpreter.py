"""Finite arithmetic only. No eval, imports, callbacks, I/O, loops or recursion."""

import json
import time
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext

from canvas_bridge.academic.contracts import unsupported


def checked(value):
    if type(value) not in {str, int, float, Decimal} or (
        isinstance(value, str) and len(value) > 64
    ):
        unsupported("Numeric extension input is invalid.")
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or abs(number) > 1_000_000_000
            or len(number.as_tuple().digits) > 28
            or abs(number.as_tuple().exponent) > 28
        ):
            unsupported("Extension arithmetic exceeded its numeric budget.")
        return number
    except (DecimalException, ValueError, TypeError):
        unsupported("Numeric extension input is invalid.")


def evaluate(manifest, inputs, *, timer=time.monotonic):
    started = timer()

    def deadline():
        if (timer() - started) * 1000 >= manifest.budget.max_milliseconds:
            unsupported("The extension exceeded its time budget.")

    if set(inputs) != set(manifest.inputs):
        unsupported("The extension input exceeds its declared schema or budget.")
    values = {key: checked(value) for key, value in inputs.items()}
    if len(json.dumps(values, default=str).encode()) > manifest.budget.max_input_bytes:
        unsupported("The extension exceeded its input budget.")
    for key, field in manifest.inputs.items():
        if not field.minimum <= values[key] <= field.maximum:
            unsupported("An extension input is outside its declared range.")
    try:
        with localcontext() as context:
            context.prec = 28
            for index, step in enumerate(manifest.steps):
                deadline()
                if index >= manifest.budget.max_steps:
                    unsupported("The extension exceeded its step budget.")
                a, b = (
                    values[o.ref] if o.ref is not None else o.constant
                    for o in (step.left, step.right)
                )
                if step.op == "add":
                    value = a + b
                elif step.op == "subtract":
                    value = a - b
                elif step.op == "multiply":
                    value = a * b
                elif step.op == "divide":
                    value = a / b
                elif step.op == "min":
                    value = min(a, b)
                elif step.op == "max":
                    value = max(a, b)
                else:
                    unsupported()
                values[step.name] = checked(value)
            result = {}
            for name, ref in manifest.emit.items():
                value = values[ref]
                field = manifest.outputs[name]
                if not field.minimum <= value <= field.maximum:
                    unsupported("An extension output is outside its declared range.")
                result[name] = str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    except DecimalException:
        unsupported("The extension calculation is undefined for these inputs.")
    deadline()
    if len(json.dumps(result).encode()) > manifest.budget.max_output_bytes:
        unsupported("The extension exceeded its output budget.")
    return result

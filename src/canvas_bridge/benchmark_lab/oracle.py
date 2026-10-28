"""Independent rational arithmetic for auditable gold formulas. No product imports."""

import ast
from fractions import Fraction


def rational(expression):
    if len(expression) > 500:
        raise ValueError("Formula too long.")
    tree = ast.parse(expression, mode="eval")

    def visit(node, depth=0):
        if depth > 20:
            raise ValueError("Formula too deep.")
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            if abs(node.value) > 1_000_000_000:
                raise ValueError("Formula literal too large.")
            return Fraction(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand, depth + 1)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise ValueError("Only literal rational arithmetic is permitted.")

    return visit(tree.body)

"""Safe evaluator for the product formulas on the sheet's `product_size_formulas` tab (spec + named parameters -> amount)."""
import ast
import operator
import re
from typing import Dict, List

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def evaluate_formula(expr: str, variables: Dict[str, float]) -> float:
    """Evaluate e.g. '(span / depth_ratio) * span' using only numbers, the given variables, + - * / **
    and parentheses. Anything else raises ValueError (sheet text is never passed to eval)."""
    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Unknown variable '{node.id}' in formula '{expr}' (have {sorted(variables)})")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](_ev(node.operand))
        raise ValueError(f"Disallowed syntax in formula '{expr}': {ast.dump(node)[:80]}")
    return _ev(ast.parse(expr.strip(), mode="eval"))


def formula_variables(expr: str) -> List[str]:
    """Names used in a formula."""
    return sorted(set(re.findall(r"[A-Za-z_]\w*", expr)))

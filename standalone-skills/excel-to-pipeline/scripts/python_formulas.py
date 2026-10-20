"""Small Python expression API retaining the tested Excel value semantics.

Generated Python constructs expressions; workbook strings are never eval/exec'd.
IF/IFERROR remain lazy and ranges retain reference semantics (SUM(A1) != SUM("2")).
"""
from formula_engine import FormulaFailure


class Expression:
    def __init__(self, node):
        self.node = node

    def binary(self, other, operator):
        return Expression(("binary", operator, self.node, node(other)))

    def __add__(self, other): return self.binary(other, "+")
    def __sub__(self, other): return self.binary(other, "-")
    def __mul__(self, other): return self.binary(other, "*")
    def __truediv__(self, other): return self.binary(other, "/")
    def __pow__(self, other): return self.binary(other, "^")
    def __neg__(self): return Expression(("unary", "-", self.node))
    def __pos__(self): return Expression(("unary", "+", self.node))


def node(value):
    return value.node if isinstance(value, Expression) else ("literal", value)


def VALUE(value):
    return Expression(node(value))


def REF(sheet, first, last=None):
    return Expression(("ref", sheet, first, last or first))


def NAME(sheet, name):
    return Expression(("name", sheet, name))


def ERROR(code):
    return Expression(("error", code))


def COMPARE(left, operator, right):
    return VALUE(left).binary(right, operator)


def CONCAT(left, right):
    return VALUE(left).binary(right, "&")


def PERCENT(value):
    return Expression(("unary", "%", node(value)))


def call(name):
    def formula(*args):
        return Expression(("call", name, [node(arg) for arg in args]))
    return formula


def UNSUPPORTED_CALL(name, *args):
    # Preserves lazy IF branches; an unknown function only fails if evaluated.
    return Expression(("call", name, [node(arg) for arg in args]))


SUM = call("SUM")
AVERAGE = call("AVERAGE")
MIN = call("MIN")
MAX = call("MAX")
COUNT = call("COUNT")
COUNTA = call("COUNTA")
IF = call("IF")
IFERROR = call("IFERROR")
ROUND = call("ROUND")
SUMIF = call("SUMIF")
SUMIFS = call("SUMIFS")
COUNTIF = call("COUNTIF")
COUNTIFS = call("COUNTIFS")
VLOOKUP = call("VLOOKUP")
AND = call("AND")
OR = call("OR")


class FormulaBook:
    """Register generated expressions before the bounded engine calculates cells."""
    def __init__(self):
        self.nodes = {}

    def set(self, sheet, address, expression):
        key = (sheet, address)
        if key in self.nodes:
            raise ValueError(f"계산 위치가 중복됩니다: {sheet}!{address}")
        self.nodes[key] = node(expression)

    def unsupported(self, sheet, address, code):
        # Keep an explicit non-success node. Never replace an unknown rule by 0.
        self.nodes[(sheet, address)] = ("unsupported", code)

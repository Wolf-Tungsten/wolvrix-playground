"""Conservative typed, two-state bit-vector normalization for semantic graph checks.

Every constructor preserves widths, signed interpretations, and mux slots.
Unsupported or partial operations raise Unverified; they never compare equal
merely because both sides are unsupported. Four-state behavior is out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from itertools import product
import re


class Unverified(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BVType:
    width: int
    signed: bool = False
    domain: str = "two"
    shape: tuple = ()

    def check(self):
        if self.domain != "two":
            raise Unverified("four_state_domain_not_proved")
        if self.width < 1:
            raise Unverified("unknown_or_zero_expression_width")
        if self.shape:
            raise Unverified("array_expression_not_scalarized")
        return self


@dataclass(frozen=True, slots=True, eq=False)
class Term:
    op: str
    type: BVType
    args: tuple = ()
    params: tuple = ()
    _digest: bytes = field(init=False, repr=False)
    _hash: int = field(init=False, repr=False)

    def __post_init__(self):
        # Hashing, ordering and equality must preserve DAG sharing. Recursive
        # dataclass hash/repr expands repeated BDD children exponentially.
        prefix = repr((self.op, self.type, self.params)).encode()
        digest = hashlib.sha256(prefix + b"".join(child._digest for child in self.args)).digest()
        object.__setattr__(self, "_digest", digest)
        object.__setattr__(self, "_hash", hash(digest))

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if not isinstance(other, Term):
            return NotImplemented
        pending, seen = [(self, other)], set()
        while pending:
            left, right = pending.pop()
            if left is right:
                continue
            pair = (id(left), id(right))
            if pair in seen:
                continue
            seen.add(pair)
            if (left._digest != right._digest or left.op != right.op or left.type != right.type
                    or left.params != right.params or len(left.args) != len(right.args)):
                return False
            pending.extend(zip(left.args, right.args))
        return True


def source(name, typ):
    return Term("source", typ.check(), (), (name,))


def constant(value, typ):
    return Term("const", typ.check(), (), (int(value) & ((1 << typ.width) - 1),))


def cast(value, typ):
    typ.check()
    if value.type.width != typ.width:
        raise Unverified("reinterpret_cast_changes_width")
    if value.type == typ:
        return value
    if value.op == "const":
        return constant(value.params[0], typ)
    if value.op == "cast":
        return cast(value.args[0], typ)
    return Term("cast", typ, (value,))


def resize(value, typ, signed_extension=None):
    typ.check()
    value.type.check()
    if value.type.width == typ.width:
        return cast(value, typ)
    if value.op == "const":
        number = value.params[0]
        if typ.width > value.type.width and (value.type.signed if signed_extension is None else signed_extension):
            number = signed_value(number, value.type.width)
        return constant(number, typ)
    if typ.width < value.type.width:
        return slice_bits(value, 0, typ.width, typ.signed)
    signed_extension = value.type.signed if signed_extension is None else signed_extension
    return Term("sext" if signed_extension else "zext", typ, (value,))


def slice_bits(value, low, width, signed=False):
    if low < 0 or width < 1 or low + width > value.type.width:
        raise Unverified("invalid_static_slice")
    typ = BVType(width, signed)
    if low == 0 and width == value.type.width:
        return cast(value, typ)
    if value.op == "const":
        return constant(value.params[0] >> low, typ)
    if value.op == "slice":
        return slice_bits(value.args[0], value.params[0] + low, width, signed)
    return Term("slice", typ, (value,), (low, width))


def boolean(value):
    if value.type.width == 1:
        return cast(value, BVType(1))
    return Term("reduce_or", BVType(1), (value,))


def signed_value(value, width):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def _same_operands(args, typ):
    return tuple(resize(arg, BVType(typ.width, arg.type.signed)) for arg in args)


def binary(op, typ, left, right):
    typ.check()
    if op in ("add", "sub", "mul", "and", "or", "xor"):
        left, right = _same_operands((left, right), typ)
    if op in ("eq", "ne", "lt", "le", "gt", "ge") and left.type.signed != right.type.signed:
        raise Unverified("mixed_signed_comparison")
    if op in ("and", "or", "xor", "add", "mul", "eq", "ne") and left._digest > right._digest:
        left, right = right, left
    return Term(op, typ, (left, right))


def mux(select, yes, no, typ):
    if select is None or yes is None or no is None:
        raise Unverified("partial_when_has_missing_branch")
    if select.type.width != 1:
        raise Unverified("mux_select_is_not_one_bit")
    select = cast(select, BVType(1))
    yes, no = resize(yes, typ), resize(no, typ)
    if select.op == "const":
        return yes if select.params[0] else no
    if yes == no:
        return yes
    if yes.op == no.op == "const" and typ.width == 1:
        if yes.params[0] == 1 and no.params[0] == 0:
            return cast(select, typ)
        if yes.params[0] == 0 and no.params[0] == 1:
            return Term("not", typ, (select,))
    return Term("mux", typ, (select, yes, no))


def concatenate(args, typ):
    if not args or sum(arg.type.width for arg in args) != typ.width:
        raise Unverified("concat_width_disagreement")
    if len(args) == 1:
        return cast(args[0], typ)
    # Recognize exactly the GRH emitter's explicit sign/zero extension shape.
    if len(args) == 2:
        high, low = args
        if high.op == "const" and high.params[0] == 0:
            return resize(low, typ, False)
        sign = high.args[0] if high.op == "replicate" else high
        if sign.op == "slice" and sign.args[0] == low and sign.params == (low.type.width - 1, 1):
            return resize(low, typ, True)
    return Term("concat", typ, tuple(args))


def _attr(attrs, name, default=None):
    result = attrs.get(name, default)
    return result.get("v", result.get("vs", default)) if isinstance(result, dict) else result


def parse_grh_constant(text, typ):
    found = re.fullmatch(r"(\d+)'([sS]?)([bBoOdDhH])([+-]?[0-9a-fA-F_]+)", str(text))
    if not found or int(found[1]) != typ.width:
        raise Unverified("unknown_or_mistyped_GRH_constant")
    try:
        return constant(int(found[4].replace("_", ""), {"b": 2, "o": 8, "d": 10, "h": 16}[found[3].lower()]), typ)
    except ValueError as error:
        raise Unverified("four_state_or_invalid_GRH_constant") from error


GRH_BINARY = {"kAdd": "add", "kSub": "sub", "kMul": "mul", "kAnd": "and", "kOr": "or", "kXor": "xor",
              "kEq": "eq", "kNe": "ne", "kLt": "lt", "kLe": "le", "kGt": "gt", "kGe": "ge"}
GSIM_BINARY = {"OP_ADD": "add", "OP_SUB": "sub", "OP_MUL": "mul", "OP_AND": "and", "OP_OR": "or", "OP_XOR": "xor",
               "OP_EQ": "eq", "OP_NEQ": "ne", "OP_LT": "lt", "OP_LEQ": "le", "OP_GT": "gt", "OP_GEQ": "ge"}


def normalize_grh(kind, typ, args, attrs=None):
    typ.check()
    attrs = attrs or {}
    args = tuple(args)
    if kind == "kConstant":
        return parse_grh_constant(_attr(attrs, "constValue"), typ)
    if kind == "kAssign":
        if len(args) != 1 or args[0].type.width != typ.width:
            raise Unverified("assign_width_changes_without_explicit_resize")
        return cast(args[0], typ)
    if kind == "kMux":
        if len(args) != 3:
            raise Unverified("invalid_mux_arity")
        return mux(*args, typ)
    if kind == "kSliceStatic":
        low, end = int(_attr(attrs, "sliceStart", -1)), int(_attr(attrs, "sliceEnd", -1))
        if len(args) != 1 or end - low + 1 != typ.width:
            raise Unverified("slice_result_width_disagreement")
        return slice_bits(args[0], low, typ.width, typ.signed)
    if kind == "kConcat":
        return concatenate(args, typ)
    if kind == "kReplicate":
        count = int(_attr(attrs, "rep", -1))
        if len(args) != 1 or count < 1 or args[0].type.width * count != typ.width:
            raise Unverified("replicate_width_disagreement")
        return Term("replicate", typ, args, (count,))
    if kind in GRH_BINARY:
        if len(args) != 2:
            raise Unverified("binary_arity_disagreement")
        return binary(GRH_BINARY[kind], typ, *args)
    if kind == "kNot" and len(args) == 1:
        return Term("not", typ, (resize(args[0], typ),))
    reductions = {"kReduceAnd": "reduce_and", "kReduceOr": "reduce_or", "kReduceXor": "reduce_xor"}
    if kind in reductions and len(args) == 1 and typ.width == 1:
        return Term(reductions[kind], typ, args)
    if kind in ("kLogicAnd", "kLogicOr") and len(args) == 2 and typ.width == 1:
        return binary("and" if kind == "kLogicAnd" else "or", typ, *(boolean(arg) for arg in args))
    if kind == "kLogicNot" and len(args) == 1 and typ.width == 1:
        return Term("not", typ, (boolean(args[0]),))
    if kind in ("kShl", "kLShr", "kAShr") and len(args) == 2:
        return Term({"kShl": "shl", "kLShr": "lshr", "kAShr": "ashr"}[kind], typ, args)
    raise Unverified("unsupported_GRH_operation:" + kind)


def normalize_gsim(op, typ, args, values=(), strVal="", head_tail_updated=False):
    typ.check()
    args = tuple(args)
    if op == "OP_INT":
        try:
            # Native firStrBase accepts decimal and the FIRRTL 0[bodh]
            # prefixes, with a preceding minus sign. Preserve that exact base.
            match = re.fullmatch(r"(-?)0([bodh])([0-9a-fA-F]+)", strVal)
            number = int(match[1] + match[3], {"b": 2, "o": 8, "d": 10, "h": 16}[match[2]]) \
                if match else int(strVal, 10)
            return constant(number, typ)
        except ValueError as error:
            raise Unverified("unknown_GSIM_constant") from error
    if any(arg is None for arg in args):
        raise Unverified("partial_when_has_missing_branch" if op == "OP_WHEN" else "missing_native_expression_child")
    if op in ("OP_MUX", "OP_WHEN"):
        if len(args) != 3:
            raise Unverified("invalid_mux_arity")
        return mux(*args, typ)
    if op in GSIM_BINARY:
        if len(args) != 2:
            raise Unverified("binary_arity_disagreement")
        left, right = args
        if op in ("OP_EQ", "OP_NEQ", "OP_LT", "OP_LEQ", "OP_GT", "OP_GEQ"):
            width = max(left.type.width, right.type.width)
            left, right = resize(left, BVType(width, left.type.signed)), resize(right, BVType(width, right.type.signed))
        return binary(GSIM_BINARY[op], typ, left, right)
    if op in ("OP_ASUINT", "OP_ASSINT", "OP_ASCLOCK", "OP_ASASYNCRESET") and len(args) == 1:
        if typ.width != args[0].type.width:
            raise Unverified("GSIM_cast_changes_width")
        return cast(args[0], typ)
    if op in ("OP_PAD", "OP_CVT") and len(args) == 1:
        return resize(args[0], typ)
    if op == "OP_SEXT" and len(args) == 1:
        if len(values) != 1 or values[0] != typ.width or typ.width < args[0].type.width:
            raise Unverified("invalid_native_sign_extension_width")
        return resize(args[0], typ, True)
    if op == "OP_NEG" and len(args) == 1:
        return binary("sub", typ, constant(0, typ), resize(args[0], typ))
    if op == "OP_NOT" and len(args) == 1:
        return Term("not", typ, (resize(args[0], typ),))
    reductions = {"OP_ANDR": "reduce_and", "OP_ORR": "reduce_or", "OP_XORR": "reduce_xor"}
    if op in reductions and len(args) == 1 and typ.width == 1:
        return Term(reductions[op], typ, args)
    if op == "OP_CAT":
        return concatenate(args, typ)
    if op in ("OP_BITS", "OP_HEAD", "OP_TAIL", "OP_SHR") and len(args) == 1:
        if op == "OP_BITS" and len(values) == 2:
            low = values[1]
        elif op == "OP_HEAD" and len(values) == 1:
            # inferAllWidth ends in Node::updateHeadTail, replacing the
            # original HEAD count by the actual right-shift amount.
            low = values[0] if head_tail_updated else args[0].type.width - values[0]
        elif op in ("OP_TAIL", "OP_SHR") and len(values) == 1:
            low = 0 if op == "OP_TAIL" else values[0]
        else:
            raise Unverified("invalid_static_slice_parameters")
        expected_width = values[0] if op == "OP_TAIL" and head_tail_updated else \
            args[0].type.width - values[0] if op == "OP_TAIL" else typ.width
        if expected_width != typ.width:
            raise Unverified("native_tail_stage_width_disagreement")
        return slice_bits(args[0], low, typ.width, typ.signed)
    if op in ("OP_SHL", "OP_DSHL", "OP_DSHR"):
        if op == "OP_SHL" and len(args) == 1 and len(values) == 1:
            args = (args[0], constant(values[0], BVType(32)))
        if len(args) != 2:
            raise Unverified("invalid_shift_arity")
        tag = "shl" if op != "OP_DSHR" else "ashr" if args[0].type.signed else "lshr"
        return Term(tag, typ, (resize(args[0], BVType(typ.width, args[0].type.signed)), args[1]))
    raise Unverified("unsupported_GSIM_operation:" + op)


def source_types(term):
    found = {}
    stack, seen = [term], set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        node.type.check()
        if node.op not in {"source", "const", "cast", "zext", "sext", "slice", "mux", "not", "and", "or", "xor",
                           "add", "sub", "mul", "eq", "ne", "lt", "le", "gt", "ge", "reduce_and", "reduce_or",
                           "reduce_xor", "concat", "replicate", "shl", "lshr", "ashr"}:
            raise Unverified("unsupported_canonical_operation:" + node.op)
        if node.op == "source":
            name = node.params[0]
            if name in found and found[name] != node.type:
                raise Unverified("same_source_has_inconsistent_width_or_sign")
            found[name] = node.type
        stack.extend(node.args)
    return found


def evaluate(term, inputs):
    @lru_cache(None)
    def run(node):
        args = [run(child) for child in node.args]
        mask = (1 << node.type.width) - 1
        op = node.op
        if op == "source":
            value = inputs[node.params[0]]
        elif op == "const":
            value = node.params[0]
        elif op in ("cast", "zext"):
            value = args[0]
        elif op == "sext":
            value = signed_value(args[0], node.args[0].type.width)
        elif op == "slice":
            value = args[0] >> node.params[0]
        elif op == "mux":
            value = args[1] if args[0] else args[2]
        elif op == "not":
            value = ~args[0]
        elif op in ("and", "or", "xor", "add", "sub", "mul"):
            a, b = args
            value = {"and": lambda: a & b, "or": lambda: a | b, "xor": lambda: a ^ b,
                     "add": lambda: a + b, "sub": lambda: a - b, "mul": lambda: a * b}[op]()
        elif op in ("eq", "ne", "lt", "le", "gt", "ge"):
            a, b = (signed_value(value, child.type.width) if child.type.signed else value
                    for value, child in zip(args, node.args))
            value = int({"eq": lambda: a == b, "ne": lambda: a != b, "lt": lambda: a < b,
                         "le": lambda: a <= b, "gt": lambda: a > b, "ge": lambda: a >= b}[op]())
        elif op.startswith("reduce_"):
            value = int(args[0] == (1 << node.args[0].type.width) - 1) if op == "reduce_and" else \
                int(bool(args[0])) if op == "reduce_or" else args[0].bit_count() & 1
        elif op == "concat":
            value = 0
            for arg, child in zip(args, node.args):
                value = (value << child.type.width) | arg
        elif op == "replicate":
            value = 0
            for _ in range(node.params[0]):
                value = (value << node.args[0].type.width) | args[0]
        elif op in ("shl", "lshr", "ashr"):
            a, amount = args
            if op == "ashr":
                a = signed_value(a, node.args[0].type.width)
            if amount >= max(node.type.width, node.args[0].type.width):
                value = -1 if op == "ashr" and a < 0 else 0
            else:
                value = a << amount if op == "shl" else a >> amount
        else:
            raise Unverified("unsupported_evaluator_operation:" + op)
        return value & mask
    return run(term)


def compare(left, right, exhaustive_bits=12):
    if left.type != right.type:
        return {"status": "different_output_type", "left_type": repr(left.type), "right_type": repr(right.type)}
    try:
        a, b = source_types(left), source_types(right)
    except Unverified as error:
        return {"status": "unverified", "reason": str(error)}
    if a != b:
        return {"status": "different_source_boundary_types", "left": {k: repr(v) for k, v in a.items()},
                "right": {k: repr(v) for k, v in b.items()}}
    if left == right:
        return {"status": "proved_typed_structural_equality", "scope": "two-state bit-vector expression at paired source cuts"}
    bits = sum(typ.width for typ in a.values())
    if bits > exhaustive_bits:
        return {"status": "unverified", "reason": "nonidentical_expression_exceeds_exhaustive_bit_budget", "input_bits": bits}
    names = sorted(a)
    for values in product(*(range(1 << a[name].width) for name in names)):
        inputs = dict(zip(names, values))
        x, y = evaluate(left, inputs), evaluate(right, inputs)
        if x != y:
            return {"status": "counterexample", "inputs": inputs, "left": x, "right": y}
    return {"status": "proved_exhaustive_two_state_equality", "input_bits": bits, "assignments": 1 << bits}

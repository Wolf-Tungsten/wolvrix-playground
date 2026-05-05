#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DUT_DIR = ROOT / "dut"
TOP = "XsComponents"
XLEN = 64
VLEN = 128
NUM_BYTES = VLEN // 8
MAX_VLMUL = 8
MASK_BITS = NUM_BYTES * MAX_VLMUL


def fir_const(width: int, value: int) -> str:
    return f"UInt<{width}>(0h{value:x})"


def fir_bits(expr: str, hi: int, lo: int) -> str:
    return f"bits({expr}, {hi}, {lo})"


def fir_cat(parts: list[str]) -> str:
    assert parts
    expr = parts[0]
    for part in parts[1:]:
        expr = f"cat({expr}, {part})"
    return expr


def fir_mux(sel: str, yes: str, no: str) -> str:
    return f"mux({sel}, {yes}, {no})"


def fir_eq(expr: str, width: int, value: int) -> str:
    return f"eq({expr}, {fir_const(width, value)})"


def fir_static_lshift(src: str, amount: int) -> str:
    if amount == 0:
        return src
    return fir_cat([fir_bits(src, XLEN - 1 - amount, 0), fir_const(amount, 0)])


def fir_static_rshift(src: str, amount: int) -> str:
    if amount == 0:
        return src
    return fir_cat([fir_const(amount, 0), fir_bits(src, XLEN - 1, amount)])


def fir_rotate_left(src: str, amount: int) -> str:
    if amount == 0:
        return src
    return fir_cat([fir_bits(src, XLEN - 1 - amount, 0), fir_bits(src, XLEN - 1, XLEN - amount)])


def fir_rotate_right(src: str, amount: int) -> str:
    if amount == 0:
        return src
    return fir_cat([fir_bits(src, amount - 1, 0), fir_bits(src, XLEN - 1, amount)])


def fir_mux_by_2bit(sel: str, values: list[str]) -> str:
    assert len(values) == 4
    expr = values[3]
    for idx in reversed(range(3)):
        expr = fir_mux(fir_eq(sel, 2, idx), values[idx], expr)
    return expr


def fir_mux_by_3bit(sel: str, values: list[str]) -> str:
    assert len(values) == 8
    expr = values[7]
    for idx in reversed(range(7)):
        expr = fir_mux(fir_eq(sel, 3, idx), values[idx], expr)
    return expr


def fir_reduce_or_bits(expr: str, width: int) -> str:
    out = fir_bits(expr, 0, 0)
    for idx in range(1, width):
        out = f"or({out}, {fir_bits(expr, idx, idx)})"
    return out


def fir_vec_from_lsb_bits(bits: list[str]) -> str:
    return fir_cat(list(reversed(bits)))


def generate_fir() -> str:
    lines: list[str] = [
        "FIRRTL version 3.3.0",
        f"circuit {TOP} :",
        f"  module {TOP} :",
        "    input clock : Clock",
        "    input reset : UInt<1>",
        "    input io_src1 : UInt<64>",
        "    input io_src2 : UInt<64>",
        "    input io_func : UInt<6>",
        "    input io_begin : UInt<8>",
        "    input io_end : UInt<8>",
        "    input io_vsew : UInt<2>",
        "    input io_maskUsed : UInt<16>",
        "    input io_vdIdx : UInt<3>",
        "    input io_fixedTaken : UInt<1>",
        "    input io_vma : UInt<1>",
        "    input io_vta : UInt<1>",
        "    output io_taken : UInt<1>",
        "    output io_mispredict : UInt<1>",
        "    output io_aluOut : UInt<64>",
        "    output io_activeEn : UInt<16>",
        "    output io_agnosticEn : UInt<16>",
        "    output io_debug : UInt<64>",
        "",
        "    regreset r_src1 : UInt<64>, clock, reset, UInt<1>(0h0)",
        "    regreset r_src2 : UInt<64>, clock, reset, UInt<1>(0h0)",
        "    regreset r_func : UInt<6>, clock, reset, UInt<1>(0h0)",
        "    connect r_src1, io_src1",
        "    connect r_src2, io_src2",
        "    connect r_func, io_func",
        "",
        "    node func_low = bits(r_func, 1, 0)",
        "    node func_mid = bits(r_func, 3, 2)",
        "    node xor64 = xor(r_src1, r_src2)",
        "    node eq_taken = eq(xor64, UInt<64>(0h0))",
        "    node unsigned_lt = lt(r_src1, r_src2)",
        "    node src1_sign = bits(r_src1, 63, 63)",
        "    node src2_sign = bits(r_src2, 63, 63)",
        "    node sign_diff = xor(src1_sign, src2_sign)",
        "    node signed_lt = mux(sign_diff, src1_sign, unsigned_lt)",
        "    node taken_base = "
        + fir_mux_by_2bit("func_low", ["eq_taken", "signed_lt", "unsigned_lt", "UInt<1>(0h0)"]),
        "    node invert_taken = bits(r_func, 2, 2)",
        "    node taken = xor(taken_base, invert_taken)",
        "    connect io_taken, taken",
        "    connect io_mispredict, xor(io_fixedTaken, taken)",
        "",
        "    node add64 = add(r_src1, r_src2)",
        "    node add64_tail = tail(add64, 1)",
        "    node and64 = and(r_src1, r_src2)",
        "    node or64 = or(r_src1, r_src2)",
        "    node xor_logic = xor64",
    ]

    shl_values = [fir_static_lshift("r_src1", n) for n in (1, 2, 3, 4)]
    shr_values = [fir_static_rshift("r_src1", n) for n in (1, 2, 3, 4)]
    rol_values = [fir_rotate_left("r_src1", n) for n in (1, 8, 16, 32)]
    ror_values = [fir_rotate_right("r_src1", n) for n in (1, 8, 16, 32)]
    lines += [
        "    node shl_sel = " + fir_mux_by_2bit("func_low", shl_values),
        "    node shr_sel = " + fir_mux_by_2bit("func_low", shr_values),
        "    node rol_sel = " + fir_mux_by_2bit("func_low", rol_values),
        "    node ror_sel = " + fir_mux_by_2bit("func_low", ror_values),
        "    node logic_sel = " + fir_mux_by_2bit("func_low", ["and64", "or64", "xor_logic", "add64_tail"]),
        "    node shift_sel = " + fir_mux_by_2bit("func_mid", ["shl_sel", "shr_sel", "rol_sel", "ror_sel"]),
        "    node alu_mix = xor(logic_sel, shift_sel)",
        "    connect io_aluOut, alu_mix",
        "",
    ]

    start_exprs = [
        "io_begin",
        fir_static_lshift("io_begin", 1).replace("64", "8"),
    ]
    # The generic shift helpers are XLEN-oriented. Build the small left shifts directly.
    start_exprs = [
        "io_begin",
        fir_cat([fir_bits("io_begin", 6, 0), fir_const(1, 0)]),
        fir_cat([fir_bits("io_begin", 5, 0), fir_const(2, 0)]),
        fir_cat([fir_bits("io_begin", 4, 0), fir_const(3, 0)]),
    ]
    end_exprs = [
        "io_end",
        fir_cat([fir_bits("io_end", 6, 0), fir_const(1, 0)]),
        fir_cat([fir_bits("io_end", 5, 0), fir_const(2, 0)]),
        fir_cat([fir_bits("io_end", 4, 0), fir_const(3, 0)]),
    ]
    lines += [
        "    node startBytes = " + fir_mux_by_2bit("io_vsew", start_exprs),
        "    node vlBytes = " + fir_mux_by_2bit("io_vsew", end_exprs),
        "    node emptyRange = not(lt(io_begin, io_end))",
        "",
    ]

    pre_bits: list[str] = []
    body_bits: list[str] = []
    tail_bits: list[str] = []
    for idx in range(MASK_BITS):
        const = fir_const(8, idx)
        pre_bits.append(f"lt({const}, startBytes)")
        ge_start = f"not(lt({const}, startBytes))"
        lt_end = f"lt({const}, vlBytes)"
        body_bits.append(f"and({ge_start}, {lt_end})")
        tail_bits.append(f"not({lt_end})")

    lines += [
        "    node prestart128 = " + fir_vec_from_lsb_bits(pre_bits),
        "    node body128 = " + fir_vec_from_lsb_bits(body_bits),
        "    node tail128 = " + fir_vec_from_lsb_bits(tail_bits),
    ]

    def segs(name: str) -> list[str]:
        return [fir_bits(name, (idx + 1) * NUM_BYTES - 1, idx * NUM_BYTES) for idx in range(MAX_VLMUL)]

    lines += [
        "    node prestartSeg = " + fir_mux_by_3bit("io_vdIdx", segs("prestart128")),
        "    node bodySeg = " + fir_mux_by_3bit("io_vdIdx", segs("body128")),
        "    node tailSeg = " + fir_mux_by_3bit("io_vdIdx", segs("tail128")),
    ]

    mask_bits: list[str] = []
    for idx in range(NUM_BYTES):
        e8 = fir_bits("io_maskUsed", idx, idx)
        e16 = fir_bits("io_maskUsed", idx // 2, idx // 2)
        e32 = fir_bits("io_maskUsed", idx // 4, idx // 4)
        e64 = fir_bits("io_maskUsed", idx // 8, idx // 8)
        mask_bits.append(fir_mux_by_2bit("io_vsew", [e8, e16, e32, e64]))

    lines += [
        "    node maskEn = " + fir_vec_from_lsb_bits(mask_bits),
        "    node maskOffEn = not(maskEn)",
        "    node activeRaw = and(bodySeg, maskEn)",
        "    node maskAgnostic = and(mux(io_vma, maskOffEn, UInt<16>(0h0)), bodySeg)",
        "    node tailAgnostic = mux(io_vta, tailSeg, UInt<16>(0h0))",
        "    node agnosticRaw = or(maskAgnostic, tailAgnostic)",
        "    connect io_activeEn, mux(emptyRange, UInt<16>(0h0), activeRaw)",
        "    connect io_agnosticEn, mux(emptyRange, UInt<16>(0h0), agnosticRaw)",
    ]

    active_or = fir_reduce_or_bits("activeRaw", NUM_BYTES)
    debug = fir_cat(
        [
            fir_bits("alu_mix", 31, 0),
            "activeRaw",
            "agnosticRaw",
        ]
    )
    # Fold in branch and mask activity to keep these paths live after simplification.
    lines += [
        "    node activeAny = " + active_or,
        "    node debugBase = " + debug,
        "    connect io_debug, xor(debugBase, cat(UInt<62>(0h0), activeAny, taken))",
        "",
    ]
    return "\n".join(lines)


def sv_bits(expr: str, hi: int, lo: int) -> str:
    return f"{expr}[{hi}:{lo}]" if hi != lo else f"{expr}[{hi}]"


def sv_cat(parts: list[str]) -> str:
    return "{" + ", ".join(parts) + "}"


def sv_lshift(src: str, amount: int) -> str:
    return src if amount == 0 else sv_cat([sv_bits(src, XLEN - 1 - amount, 0), f"{amount}'b0"])


def sv_rshift(src: str, amount: int) -> str:
    return src if amount == 0 else sv_cat([f"{amount}'b0", sv_bits(src, XLEN - 1, amount)])


def sv_rol(src: str, amount: int) -> str:
    return src if amount == 0 else sv_cat([sv_bits(src, XLEN - 1 - amount, 0), sv_bits(src, XLEN - 1, XLEN - amount)])


def sv_ror(src: str, amount: int) -> str:
    return src if amount == 0 else sv_cat([sv_bits(src, amount - 1, 0), sv_bits(src, XLEN - 1, amount)])


def generate_sv() -> str:
    lines: list[str] = [
        "module XsComponents(",
        "  input  logic        clock,",
        "  input  logic        reset,",
        "  input  logic [63:0] io_src1,",
        "  input  logic [63:0] io_src2,",
        "  input  logic [5:0]  io_func,",
        "  input  logic [7:0]  io_begin,",
        "  input  logic [7:0]  io_end,",
        "  input  logic [1:0]  io_vsew,",
        "  input  logic [15:0] io_maskUsed,",
        "  input  logic [2:0]  io_vdIdx,",
        "  input  logic        io_fixedTaken,",
        "  input  logic        io_vma,",
        "  input  logic        io_vta,",
        "  output logic        io_taken,",
        "  output logic        io_mispredict,",
        "  output logic [63:0] io_aluOut,",
        "  output logic [15:0] io_activeEn,",
        "  output logic [15:0] io_agnosticEn,",
        "  output logic [63:0] io_debug",
        ");",
        "  logic [63:0] r_src1, r_src2;",
        "  logic [5:0] r_func;",
        "",
        "  always_ff @(posedge clock) begin",
        "    if (reset) begin",
        "      r_src1 <= 64'h0;",
        "      r_src2 <= 64'h0;",
        "      r_func <= 6'h0;",
        "    end else begin",
        "      r_src1 <= io_src1;",
        "      r_src2 <= io_src2;",
        "      r_func <= io_func;",
        "    end",
        "  end",
        "",
        "  logic [1:0] func_low;",
        "  logic [1:0] func_mid;",
        "  logic [63:0] xor64;",
        "  logic eq_taken, unsigned_lt, signed_lt, taken_base, invert_taken;",
        "  assign func_low = r_func[1:0];",
        "  assign func_mid = r_func[3:2];",
        "  assign xor64 = r_src1 ^ r_src2;",
        "  assign eq_taken = xor64 == 64'h0;",
        "  assign unsigned_lt = r_src1 < r_src2;",
        "  assign signed_lt = (r_src1[63] ^ r_src2[63]) ? r_src1[63] : unsigned_lt;",
        "  always_comb begin",
        "    unique case (func_low)",
        "      2'd0: taken_base = eq_taken;",
        "      2'd1: taken_base = signed_lt;",
        "      2'd2: taken_base = unsigned_lt;",
        "      default: taken_base = 1'b0;",
        "    endcase",
        "  end",
        "  assign invert_taken = r_func[2];",
        "  assign io_taken = taken_base ^ invert_taken;",
        "  assign io_mispredict = io_fixedTaken ^ io_taken;",
        "",
        "  logic [63:0] logic_sel, shift_sel, shl_sel, shr_sel, rol_sel, ror_sel;",
        "  always_comb begin",
        "    unique case (func_low)",
        "      2'd0: logic_sel = r_src1 & r_src2;",
        "      2'd1: logic_sel = r_src1 | r_src2;",
        "      2'd2: logic_sel = r_src1 ^ r_src2;",
        "      default: logic_sel = r_src1 + r_src2;",
        "    endcase",
        "    unique case (func_low)",
        f"      2'd0: shl_sel = {sv_lshift('r_src1', 1)};",
        f"      2'd1: shl_sel = {sv_lshift('r_src1', 2)};",
        f"      2'd2: shl_sel = {sv_lshift('r_src1', 3)};",
        f"      default: shl_sel = {sv_lshift('r_src1', 4)};",
        "    endcase",
        "    unique case (func_low)",
        f"      2'd0: shr_sel = {sv_rshift('r_src1', 1)};",
        f"      2'd1: shr_sel = {sv_rshift('r_src1', 2)};",
        f"      2'd2: shr_sel = {sv_rshift('r_src1', 3)};",
        f"      default: shr_sel = {sv_rshift('r_src1', 4)};",
        "    endcase",
        "    unique case (func_low)",
        f"      2'd0: rol_sel = {sv_rol('r_src1', 1)};",
        f"      2'd1: rol_sel = {sv_rol('r_src1', 8)};",
        f"      2'd2: rol_sel = {sv_rol('r_src1', 16)};",
        f"      default: rol_sel = {sv_rol('r_src1', 32)};",
        "    endcase",
        "    unique case (func_low)",
        f"      2'd0: ror_sel = {sv_ror('r_src1', 1)};",
        f"      2'd1: ror_sel = {sv_ror('r_src1', 8)};",
        f"      2'd2: ror_sel = {sv_ror('r_src1', 16)};",
        f"      default: ror_sel = {sv_ror('r_src1', 32)};",
        "    endcase",
        "    unique case (func_mid)",
        "      2'd0: shift_sel = shl_sel;",
        "      2'd1: shift_sel = shr_sel;",
        "      2'd2: shift_sel = rol_sel;",
        "      default: shift_sel = ror_sel;",
        "    endcase",
        "  end",
        "  assign io_aluOut = logic_sel ^ shift_sel;",
        "",
        "  logic [7:0] startBytes, vlBytes;",
        "  always_comb begin",
        "    unique case (io_vsew)",
        "      2'd0: begin startBytes = io_begin; vlBytes = io_end; end",
        "      2'd1: begin startBytes = {io_begin[6:0], 1'b0}; vlBytes = {io_end[6:0], 1'b0}; end",
        "      2'd2: begin startBytes = {io_begin[5:0], 2'b0}; vlBytes = {io_end[5:0], 2'b0}; end",
        "      default: begin startBytes = {io_begin[4:0], 3'b0}; vlBytes = {io_end[4:0], 3'b0}; end",
        "    endcase",
        "  end",
        "  logic [127:0] prestart128, body128, tail128;",
        "  genvar i;",
        "  generate",
        "    for (i = 0; i < 128; i = i + 1) begin : gen_masks",
        "      assign prestart128[i] = i[7:0] < startBytes;",
        "      assign body128[i] = (i[7:0] >= startBytes) & (i[7:0] < vlBytes);",
        "      assign tail128[i] = i[7:0] >= vlBytes;",
        "    end",
        "  endgenerate",
        "  logic [15:0] prestartSeg, bodySeg, tailSeg;",
        "  always_comb begin",
        "    prestartSeg = prestart128[io_vdIdx * 16 +: 16];",
        "    bodySeg = body128[io_vdIdx * 16 +: 16];",
        "    tailSeg = tail128[io_vdIdx * 16 +: 16];",
        "  end",
        "  logic [15:0] maskEn;",
        "  generate",
        "    for (i = 0; i < 16; i = i + 1) begin : gen_mask_extract",
        "      always_comb begin",
        "        unique case (io_vsew)",
        "          2'd0: maskEn[i] = io_maskUsed[i];",
        "          2'd1: maskEn[i] = io_maskUsed[i / 2];",
        "          2'd2: maskEn[i] = io_maskUsed[i / 4];",
        "          default: maskEn[i] = io_maskUsed[i / 8];",
        "        endcase",
        "      end",
        "    end",
        "  endgenerate",
        "  logic [15:0] activeRaw, agnosticRaw;",
        "  assign activeRaw = bodySeg & maskEn;",
        "  assign agnosticRaw = ((io_vma ? ~maskEn : 16'h0) & bodySeg) | (io_vta ? tailSeg : 16'h0);",
        "  assign io_activeEn = (io_begin >= io_end) ? 16'h0 : activeRaw;",
        "  assign io_agnosticEn = (io_begin >= io_end) ? 16'h0 : agnosticRaw;",
        "  assign io_debug = {io_aluOut[31:0], activeRaw, agnosticRaw} ^ {62'h0, |activeRaw, io_taken};",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def generate_scala() -> str:
    return """package xscomponents

import chisel3._
import chisel3.util._

// Standalone extracts of XiangShan-style branch, ALU shift/rotate, and vector
// mask-tail logic. The shape mirrors small pieces from BranchModule,
// AluDataModule, ByteMaskTailGen, and MaskExtractor without pulling the full
// XiangShan parameter graph into this testcase.
class XsComponents extends Module {
  val io = IO(new Bundle {
    val src1 = Input(UInt(64.W))
    val src2 = Input(UInt(64.W))
    val func = Input(UInt(6.W))
    val begin = Input(UInt(8.W))
    val end = Input(UInt(8.W))
    val vsew = Input(UInt(2.W))
    val maskUsed = Input(UInt(16.W))
    val vdIdx = Input(UInt(3.W))
    val fixedTaken = Input(Bool())
    val vma = Input(Bool())
    val vta = Input(Bool())
    val taken = Output(Bool())
    val mispredict = Output(Bool())
    val aluOut = Output(UInt(64.W))
    val activeEn = Output(UInt(16.W))
    val agnosticEn = Output(UInt(16.W))
    val debug = Output(UInt(64.W))
  })

  val src1 = RegNext(io.src1, 0.U)
  val src2 = RegNext(io.src2, 0.U)
  val func = RegNext(io.func, 0.U)

  val xor64 = src1 ^ src2
  val unsignedLt = src1 < src2
  val signedLt = Mux(src1(63) ^ src2(63), src1(63), unsignedLt)
  val takenBase = MuxLookup(func(1, 0), false.B)(Seq(
    0.U -> !xor64.orR,
    1.U -> signedLt,
    2.U -> unsignedLt,
  ))
  io.taken := takenBase ^ func(2)
  io.mispredict := io.fixedTaken ^ io.taken

  val logicSel = MuxLookup(func(1, 0), src1 + src2)(Seq(
    0.U -> (src1 & src2),
    1.U -> (src1 | src2),
    2.U -> (src1 ^ src2),
  ))
  val shlSel = VecInit(Seq(1, 2, 3, 4).map(n => Cat(src1(63 - n, 0), 0.U(n.W))))(func(1, 0))
  val shrSel = VecInit(Seq(1, 2, 3, 4).map(n => Cat(0.U(n.W), src1(63, n))))(func(1, 0))
  val rolSel = VecInit(Seq(1, 8, 16, 32).map(n => Cat(src1(63 - n, 0), src1(63, 64 - n))))(func(1, 0))
  val rorSel = VecInit(Seq(1, 8, 16, 32).map(n => Cat(src1(n - 1, 0), src1(63, n))))(func(1, 0))
  val shiftSel = VecInit(Seq(shlSel, shrSel, rolSel, rorSel))(func(3, 2))
  io.aluOut := logicSel ^ shiftSel

  val startBytes = VecInit(Seq.tabulate(4)(x => io.begin(7 - x, 0) << x))(io.vsew)
  val vlBytes = VecInit(Seq.tabulate(4)(x => io.end(7 - x, 0) << x))(io.vsew)
  val body128 = VecInit((0 until 128).map(i => i.U >= startBytes && i.U < vlBytes)).asUInt
  val tail128 = VecInit((0 until 128).map(i => i.U >= vlBytes)).asUInt
  val bodySeg = VecInit((0 until 8).map(i => body128((i + 1) * 16 - 1, i * 16)))(io.vdIdx)
  val tailSeg = VecInit((0 until 8).map(i => tail128((i + 1) * 16 - 1, i * 16)))(io.vdIdx)
  val maskEn = VecInit((0 until 16).map { i =>
    MuxLookup(io.vsew, io.maskUsed(i / 8))(Seq(
      0.U -> io.maskUsed(i),
      1.U -> io.maskUsed(i / 2),
      2.U -> io.maskUsed(i / 4),
    ))
  }).asUInt
  val activeRaw = bodySeg & maskEn
  val agnosticRaw = (Mux(io.vma, ~maskEn, 0.U) & bodySeg) | Mux(io.vta, tailSeg, 0.U)
  io.activeEn := Mux(io.begin >= io.end, 0.U, activeRaw)
  io.agnosticEn := Mux(io.begin >= io.end, 0.U, agnosticRaw)
  io.debug := Cat(io.aluOut(31, 0), activeRaw, agnosticRaw) ^ Cat(0.U(62.W), activeRaw.orR, io.taken)
}

object XsComponentsMain extends App {
  import chisel3.stage.ChiselGeneratorAnnotation
  import _root_.circt.stage.ChiselStage

  (new ChiselStage).execute(args, Seq(
    ChiselGeneratorAnnotation(() => new XsComponents)
  ))
}
"""


def main() -> int:
    DUT_DIR.mkdir(parents=True, exist_ok=True)
    (DUT_DIR / f"{TOP}.fir").write_text(generate_fir(), encoding="ascii")
    (DUT_DIR / f"{TOP}.sv").write_text(generate_sv(), encoding="ascii")
    (ROOT / "src" / "main" / "scala").mkdir(parents=True, exist_ok=True)
    (ROOT / "src" / "main" / "scala" / f"{TOP}.scala").write_text(generate_scala(), encoding="ascii")
    print(f"generated {DUT_DIR / f'{TOP}.fir'}")
    print(f"generated {DUT_DIR / f'{TOP}.sv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

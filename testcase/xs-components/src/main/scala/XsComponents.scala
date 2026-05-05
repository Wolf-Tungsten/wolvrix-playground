package xscomponents

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

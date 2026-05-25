package xscomponents

import chisel3._
import chisel3.util._

// Extracted from vector byte mask and tail generation in
// xiangshan/backend/fu/vector/ByteMaskTailGen.scala and
// xiangshan/mem/vector/VecCommon.scala.
class XsVectorMaskMedium extends XsComponentModule {
  import XsCommon._

  val begin = io.in0(7, 0)
  val end = io.in1(7, 0)
  val vsew = io.ctrl(1, 0)
  val vdIdx = io.ctrl(4, 2)
  val maskUsed = io.in2(15, 0)
  val vma = io.ctrl(5)
  val vta = io.ctrl(6)
  val startBytes = VecInit(Seq.tabulate(4)(i => (begin(7 - i, 0) << i).asUInt))(vsew)
  val vlBytes = VecInit(Seq.tabulate(4)(i => (end(7 - i, 0) << i).asUInt))(vsew)
  val body128 = VecInit((0 until 128).map(i => i.U >= startBytes && i.U < vlBytes)).asUInt
  val tail128 = VecInit((0 until 128).map(i => i.U >= vlBytes)).asUInt
  val bodySeg = VecInit((0 until 8).map(i => body128((i + 1) * 16 - 1, i * 16)))(vdIdx)
  val tailSeg = VecInit((0 until 8).map(i => tail128((i + 1) * 16 - 1, i * 16)))(vdIdx)
  val maskEn = VecInit((0 until 16).map { i =>
    MuxLookup(vsew, maskUsed(i / 8))(Seq(
      0.U -> maskUsed(i),
      1.U -> maskUsed(i / 2),
      2.U -> maskUsed(i / 4),
    ))
  }).asUInt
  val activeRaw = bodySeg & maskEn
  val agnosticRaw = (Mux(vma, ~maskEn, 0.U) & bodySeg) | Mux(vta, tailSeg, 0.U)
  val empty = begin >= end
  val active = Mux(empty, 0.U, activeRaw)
  val agnostic = Mux(empty, 0.U, agnosticRaw)
  val crossMask = Cat(active ^ agnostic, active)

  io.out0 := Cat(0.U(48.W), active)
  io.out1 := Cat(0.U(48.W), agnostic)
  io.out2 := Cat(0.U(32.W), crossMask)
  io.out3 := mix64(Cat(0.U(48.W), active), Cat(0.U(48.W), agnostic), 11)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}


package xscomponents

import chisel3._
import chisel3.util._

// Extracted from PLRU-like replacement logic in
// utility/Replacement.scala and coupledL2/utils/Replacer.scala.
class XsPlruLarge extends XsComponentModule {
  import XsCommon._

  val state = io.in0(62, 0)
  val touchOH = UIntToOH(io.ctrl(5, 0), 64)
  val wayMask = io.in1
  val validMask = io.in2
  val candidates = wayMask & validMask
  val victimOH = PriorityEncoderOH(VecInit((0 until 64).map(i => {
    val bit = candidates(i)
    val stateBit = state((i * 7 + 3) % 63)
    bit && !stateBit
  })).asUInt | PriorityEncoderOH(candidates))
  val nextStateBits = VecInit((0 until 63).map(i => {
    val touched = (touchOH & ((BigInt(1) << ((i % 32) + 1)) - 1).U(64.W)).orR
    state(i) ^ touched ^ io.ctrl((i % 16) + 8)
  })).asUInt
  val refillMask = VecInit((0 until 64).map(i => victimOH(i) ^ touchOH(i) ^ state(i % 63))).asUInt

  io.out0 := victimOH
  io.out1 := refillMask
  io.out2 := Cat(0.U(1.W), nextStateBits)
  io.out3 := mix64(refillMask, Cat(0.U(1.W), nextStateBits), 23)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

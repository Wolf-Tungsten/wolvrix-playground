package xscomponents

import chisel3._
import chisel3.util._

// Extracted from issue/load-queue age selection patterns in
// xiangshan/backend/issue/AgeDetector.scala and
// xiangshan/mem/lsqueue/LoadQueueReplay.scala.
class XsAgeMatrixMedium extends XsComponentModule {
  import XsCommon._

  val valid = io.in0(31, 0)
  val enq = io.in1(31, 0)
  val ready = io.in2(31, 0)
  val blocked = io.in3(31, 0)
  val ageSeed = io.in4(31, 0) ^ io.ctrl(31, 0)
  val live = (valid | enq) & ready & ~blocked
  val rotated = VecInit((0 until 32).map(i => (live.rotateRight(i) & ageSeed).orR))
  val priority = PriorityEncoderOH(live)
  val oldest = PriorityEncoderOH(rotated.asUInt)
  val grant = priority | oldest
  val replay = VecInit((0 until 32).map(i => {
    val older = live(i) && (live & ((BigInt(1) << i) - 1).U(32.W)).orR
    older ^ ageSeed(i)
  })).asUInt

  io.out0 := Cat(0.U(32.W), live)
  io.out1 := Cat(0.U(32.W), grant)
  io.out2 := Cat(0.U(32.W), replay)
  io.out3 := mix64(Cat(0.U(32.W), live), Cat(0.U(32.W), replay), 17)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}


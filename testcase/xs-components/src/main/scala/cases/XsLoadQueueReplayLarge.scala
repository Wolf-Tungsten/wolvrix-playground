package xscomponents

import chisel3._
import chisel3.util._

// Extracted from LoadQueueReplay.scala and LoadQueue RAW/RAR mask selection:
// dense valid/ready/cause vectors, replay priority, and rotating age filters.
class XsLoadQueueReplayLarge extends XsComponentModule {
  import XsCommon._

  private val entries = 64

  val valid = io.in0
  val addrReady = io.in1
  val dataReady = io.in2
  val sleep = io.in3
  val violation = io.in4
  val wakeMask = io.in5
  val start = io.ctrl(5, 0)
  val replayCause = VecInit((0 until entries).map(i => io.ctrl((i % 8) + 8) ^ violation(i)))
  val live = valid & addrReady & ~sleep
  val needReplay = live & (wakeMask | violation | ~dataReady)
  val rotated = VecInit((0 until entries).map(i => needReplay((i.U(6.W) + start)(5, 0)))).asUInt
  val firstRot = PriorityEncoderOH(rotated)
  val grant = VecInit((0 until entries).map(i => firstRot((i.U(6.W) - start)(5, 0)))).asUInt
  val olderMask = Wire(Vec(entries, Bool()))

  for (i <- 0 until entries) {
    val lower = if (i == 0) 0.U(entries.W) else needReplay(i - 1, 0)
    olderMask(i) := lower.orR ^ replayCause(i)
  }

  val replayVec = VecInit((0 until entries).map(i => needReplay(i) && olderMask(i))).asUInt | grant
  val bankConflict = VecInit((0 until 8).map(bank => {
    val hits = VecInit((0 until entries by 8).map(offset => needReplay(bank + offset))).asUInt
    PopCount(hits) > 1.U
  })).asUInt

  io.out0 := live
  io.out1 := needReplay
  io.out2 := replayVec
  io.out3 := Cat(0.U(56.W), bankConflict)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

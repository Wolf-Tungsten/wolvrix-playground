package xscomponents

import chisel3._
import chisel3.util._

// Extracted from the branch-compare and ALU datapath shape used by
// xiangshan/backend/fu/wrapper/BranchUnit.scala and
// xiangshan/backend/fu/Alu.scala.
class XsBranchAluSmall extends XsComponentModule {
  import XsCommon._

  val src1 = RegNext(io.in0, 0.U(64.W))
  val src2 = RegNext(io.in1, 0.U(64.W))
  val pc = RegNext(io.in2, 0.U(64.W))
  val func = RegNext(io.ctrl(5, 0), 0.U(6.W))

  val unsignedLt = src1 < src2
  val signedLt = Mux(src1(63) ^ src2(63), src1(63), unsignedLt)
  val takenBase = MuxLookup(func(1, 0), false.B)(Seq(
    0.U -> !(src1 ^ src2).orR,
    1.U -> signedLt,
    2.U -> unsignedLt,
    3.U -> src1(0),
  ))
  val taken = takenBase ^ func(2)
  val logic = MuxLookup(func(1, 0), src1 + src2)(Seq(
    0.U -> (src1 & src2),
    1.U -> (src1 | src2),
    2.U -> (src1 ^ src2),
  ))
  val shift = VecInit(Seq(
    Cat(src1(62, 0), 0.U(1.W)),
    Cat(0.U(2.W), src1(63, 2)),
    rotl(src1, 13),
    rotr(src1, 7),
  ))(func(1, 0))
  val target = pc + Cat(src2(51, 0), 0.U(1.W))

  io.out0 := logic ^ shift
  io.out1 := target
  io.out2 := Cat(0.U(63.W), taken)
  io.out3 := mix64(logic, target, 3)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}


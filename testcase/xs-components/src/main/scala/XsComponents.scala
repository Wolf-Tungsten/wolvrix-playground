package xscomponents

import chisel3._
import chisel3.util._

class XsComponentIO extends Bundle {
  val in0 = Input(UInt(64.W))
  val in1 = Input(UInt(64.W))
  val in2 = Input(UInt(64.W))
  val in3 = Input(UInt(64.W))
  val in4 = Input(UInt(64.W))
  val in5 = Input(UInt(64.W))
  val ctrl = Input(UInt(64.W))
  val out0 = Output(UInt(64.W))
  val out1 = Output(UInt(64.W))
  val out2 = Output(UInt(64.W))
  val out3 = Output(UInt(64.W))
  val flags = Output(UInt(64.W))
  val checksum = Output(UInt(64.W))
}

abstract class XsComponentModule extends Module {
  val io = IO(new XsComponentIO)
}

object XsCommon {
  def rotl(x: UInt, n: Int): UInt = Cat(x(63 - n, 0), x(63, 64 - n))
  def rotr(x: UInt, n: Int): UInt = Cat(x(n - 1, 0), x(63, n))

  def mix64(a: UInt, b: UInt, salt: Int): UInt = {
    val x = a ^ rotl(b, (salt % 31) + 1) ^ (BigInt("9e3779b97f4a7c15", 16) + salt).U(64.W)
    val y = x + rotr(a ^ b, (salt % 17) + 1)
    y ^ rotl(y, (salt % 23) + 1)
  }

  def fold(values: Seq[UInt]): UInt = {
    var acc = values.head
    for ((value, idx) <- values.tail.zipWithIndex) {
      acc = mix64(acc, value, idx + 1)
    }
    acc
  }
}

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
  val grantIndex = PriorityEncoder(grant)

  io.out0 := Cat(0.U(32.W), live)
  io.out1 := Cat(0.U(32.W), grant)
  io.out2 := Cat(0.U(32.W), replay)
  io.out3 := mix64(Cat(0.U(32.W), live), Cat(0.U(32.W), replay), 17)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from PLRU-like replacement logic in
// utility/Replacement.scala and coupledL2/utils/Replacer.scala.
class XsPlruLarge extends XsComponentModule {
  import XsCommon._

  val state = RegNext(io.in0(62, 0), 0.U(63.W))
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
  val victimIdx = PriorityEncoder(victimOH)
  val refillMask = VecInit((0 until 64).map(i => victimOH(i) ^ touchOH(i) ^ state(i % 63))).asUInt

  io.out0 := victimOH
  io.out1 := refillMask
  io.out2 := Cat(0.U(1.W), nextStateBits)
  io.out3 := mix64(refillMask, Cat(0.U(1.W), nextStateBits), 23)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from store-buffer byte merge and cross-16-byte mask handling in
// xiangshan/mem/sbuffer/Sbuffer.scala and xiangshan/mem/lsqueue/StoreQueue.scala.
class XsStoreMergeLarge extends XsComponentModule {
  import XsCommon._

  val oldLo = io.in0
  val oldHi = io.in1
  val dataLo = io.in2
  val dataHi = io.in3
  val mask = io.in4(15, 0)
  val addrLow = io.ctrl(3, 0)
  val crossMaskBase = Cat(0.U(16.W), mask)
  val crossMask = VecInit((0 until 16).map(i => (crossMaskBase << i)(31, 0)))(addrLow)
  def byteMerge(oldData: UInt, newData: UInt, maskBits: UInt): UInt =
    VecInit((0 until 8).map(i => Mux(maskBits(i), newData(8 * i + 7, 8 * i), oldData(8 * i + 7, 8 * i)))).asUInt
  val mergedLo = byteMerge(oldLo, dataLo, crossMask(7, 0))
  val mergedHi = byteMerge(oldHi, dataHi, crossMask(15, 8))
  val forwardLo = byteMerge(mergedLo, dataHi, crossMask(23, 16))
  val forwardHi = byteMerge(mergedHi, dataLo, crossMask(31, 24))
  val hazardVec = VecInit((0 until 16).map(i => crossMask(i) && crossMask((i + 8) % 32))).asUInt

  io.out0 := mergedLo
  io.out1 := mergedHi
  io.out2 := forwardLo
  io.out3 := forwardHi
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

object XsComponentsMain extends App {
  import chisel3.stage.ChiselGeneratorAnnotation
  import _root_.circt.stage.ChiselStage

  val tops = Map[String, () => RawModule](
    "XsBranchAluSmall" -> (() => new XsBranchAluSmall),
    "XsVectorMaskMedium" -> (() => new XsVectorMaskMedium),
    "XsAgeMatrixMedium" -> (() => new XsAgeMatrixMedium),
    "XsPlruLarge" -> (() => new XsPlruLarge),
    "XsStoreMergeLarge" -> (() => new XsStoreMergeLarge),
  )

  val top = args.sliding(2).collectFirst { case Array("--top-name", name) => name }.getOrElse("XsBranchAluSmall")
  val filteredArgs = args.toSeq.sliding(2).foldLeft(args.toSeq) {
    case (acc, Seq("--top-name", name)) => acc.filterNot(x => x == "--top-name" || x == name)
    case (acc, _) => acc
  }
  val gen = tops.getOrElse(top, sys.error(s"unknown xs-component top '$top'"))
  (new ChiselStage).execute(filteredArgs.toArray, Seq(ChiselGeneratorAnnotation(gen)))
}

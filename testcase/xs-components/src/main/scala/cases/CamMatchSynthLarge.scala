package xscomponents

import chisel3._
import chisel3.util._

// Synthetic isolation of the XiangShan ROB per-entry write-back CAM match net
// (testcase/xiangshan src/main/scala/xiangshan/backend/rob/Rob.scala:1024-1087):
// for every entry, a one-hot decode of each write-back port's robIdx, valid
// gating, Mux1H / OrR aggregation, and per-entry register updates
// (uopNum/needFlush/fflags/realDestSize), so the match net feeds register
// write ports and lands in the General phase. Three write-back families share
// the same idx sources to reproduce the cross-family CSE-shared eq
// temporaries seen in the firtool SV output.
//
// Port convention follows tb/xs_component_bench.hpp: in0..in5/ctrl in,
// out0..out3/flags/checksum out.
class CamMatchSynthLarge extends Module {
  private val P = 26 // write-back ports (exuWBs family)
  private val Q = 8 // enqueue ports (robIdxMatchSeq family)
  private val E = 352 // entries (RobSize)
  private val IW = 9 // log2Ceil(352)

  val io = IO(new Bundle {
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
  })

  // ---- input expansion: derive per-port descriptors from the 7x64 input bits
  // in2: wbValid[25:0], enqValid[63:56], num windows in [55:26]
  // in3: wbFlValid[25:0], enqNeedRF[63:56], fflags windows in [55:26]
  // in4: wbFwValid[25:0], wbNeedFlush[51:26]
  // in5: wbWflags[25:0], enqUopNum windows in [63:26]
  private def win(x: UInt, off: Int, w: Int): UInt = (x >> off)(w - 1, 0)
  private val wbValid = io.in2(P - 1, 0)
  private val wbFlValid = io.in3(P - 1, 0)
  private val wbFwValid = io.in4(P - 1, 0)
  private val wbNeedFlush = io.in4(2 * P - 1, P)
  private val wbWflags = io.in5(P - 1, 0)
  private val wbIdx = Seq.tabulate(P)(p => (win(io.in0, (p * 9) % 56, 9) ^ win(io.in1, (p * 13) % 56, 9))(IW - 1, 0))
  private val wbNum = Seq.tabulate(P)(p => win(io.in2, 26 + (p * 5) % 26, 5))
  private val wbFflags = Seq.tabulate(P)(p => win(io.in3, 26 + (p * 5) % 26, 5))
  private val enqValid = io.in2(63, 64 - Q)
  private val enqNeedRF = io.in3(63, 64 - Q)
  private val enqIdx = Seq.tabulate(Q)(q => (win(io.ctrl, (q * 7) % 56, 9) ^ win(io.in1, (q * 17 + 5) % 56, 9))(IW - 1, 0))
  private val enqUopNum = Seq.tabulate(Q)(q => win(io.in5, 26 + (q * 4) % 33, 5))

  // ---- per-entry state columns (the match net's consumers)
  private val entryValid = RegInit(VecInit(Seq.fill(E)(false.B)))
  private val uopNum = RegInit(VecInit(Seq.fill(E)(0.U(5.W))))
  private val fflagsReg = RegInit(VecInit(Seq.fill(E)(0.U(5.W))))
  private val needFlushReg = RegInit(VecInit(Seq.fill(E)(false.B)))
  private val realDestSize = RegInit(VecInit(Seq.fill(E)(0.U(4.W))))

  for (e <- 0 until E) {
    // family A: exuWBs write-back match (Rob.scala:1043-1044)
    val canWbSeq = Seq.tabulate(P)(p => wbValid(p) && wbIdx(p) === e.U)
    val wbCnt = Mux1H(canWbSeq, wbNum)
    // family B: exception flush match, shares the same eq (Rob.scala:1047)
    val canExcpSeq = Seq.tabulate(P)(p => wbFlValid(p) && wbIdx(p) === e.U)
    val needFlushWriteBack = Mux1H(canExcpSeq, wbNeedFlush.asBools)
    // family C: fflags accumulate, three-input and + fold-or (Rob.scala:1068)
    val fflagsCanWbSeq = Seq.tabulate(P)(p => wbFwValid(p) && wbIdx(p) === e.U && wbWflags(p))
    val fflagsRes = fflagsCanWbSeq.zip(wbFflags).map { case (c, f) => Mux(c, f, 0.U) }.fold(0.U)(_ | _)
    // enq family: robIdxMatchSeq + PopCount (Rob.scala:1027-1037)
    val robIdxMatchSeq = Seq.tabulate(Q)(q => enqIdx(q) === e.U)
    val uopCanEnqSeq = enqValid.asBools.zip(robIdxMatchSeq).map { case (v, m) => v && m }
    val instCanEnqFlag = uopCanEnqSeq.reduce(_ || _)
    val realDestEnqNum = PopCount(enqNeedRF.asBools.zip(uopCanEnqSeq).map { case (w, v) => w && v })
    val enqWBNum = PriorityMux(uopCanEnqSeq, enqUopNum)

    val isFirstEnq = !entryValid(e) && instCanEnqFlag
    when(entryValid(e)) {
      needFlushReg(e) := needFlushReg(e) || needFlushWriteBack
    }
    when(isFirstEnq) {
      entryValid(e) := true.B
      uopNum(e) := enqWBNum
      fflagsReg(e) := 0.U
      realDestSize(e) := realDestEnqNum
    }.elsewhen(entryValid(e) && (needFlushReg(e) || needFlushWriteBack)) {
      uopNum(e) := uopNum(e) - wbCnt
    }.elsewhen(entryValid(e)) {
      uopNum(e) := uopNum(e) - wbCnt
    }
    when(!isFirstEnq && fflagsRes.orR) {
      fflagsReg(e) := fflagsReg(e) | fflagsRes
    }
  }

  // ---- observable folds
  private val checksumReg = RegInit(0.U(64.W))
  private val validCnt = PopCount(entryValid)
  private val uopFold = uopNum.map(x => Cat(0.U(59.W), x)).reduce(_ ^ _)
  private val ffFold = fflagsReg.map(x => Cat(0.U(59.W), x)).reduce(_ ^ _)
  private val nfFold = needFlushReg.map(x => x.asUInt).reduce(_ ^ _)
  private val rdFold = realDestSize.map(x => Cat(0.U(60.W), x)).reduce(_ ^ _)
  io.out0 := uopFold ^ validCnt
  io.out1 := ffFold
  io.out2 := nfFold
  io.out3 := rdFold
  io.flags := validCnt
  checksumReg := checksumReg ^ uopFold ^ (ffFold << 1) ^ nfFold ^ (rdFold << 2)
  io.checksum := checksumReg
}

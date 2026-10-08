package xscomponents

import chisel3._
import chisel3.util._

// Synthetic isolation of the XiangShan ROB per-entry fflags write-back merge
// network (testcase/xiangshan src/main/scala/xiangshan/backend/rob/Rob.scala:1066-1071):
//   val fflagsCanWbSeq = fflags_wb.map(wb => wb.valid && wb.bits.robIdx.value === i.U && wb.bits.wflags)
//   val fflagsRes = fflagsCanWbSeq.zip(fflags_wb).map { case (c, wb) => Mux(c, wb.bits.fflags, 0.U) }.fold(false.B)(_ | _)
//   when(isFirstEnq) { robEntries(i).fflags := 0.U } .elsewhen(fflagsRes.orR) { robEntries(i).fflags := robEntries(i).fflags | fflagsRes }
//
// Mechanism under test: in the real ROB, gsim keeps robEntries.fflags as ONE
// array node (it is read through a dynamic deq-pointer index), so all 352
// per-element conditional writes live on a single $NEXT node; every per-entry
// match cone then has a unique successor and mergeOut1 absorbs the whole
// family into one ~7000-member supernode. CamMatchSynthLarge did NOT reproduce
// this because its Vec reg is only statically indexed and gsim splitArray
// scalarizes it into 352 independent registers.
//
// dynRead = true  -> array survives as one node (expect one giant supernode)
// dynRead = false -> pure static indexing (control arm: expect split, no giant)
//
// Port convention follows tb/xs_component_bench.hpp: in0..in5/ctrl in,
// out0..out3/flags/checksum out.
class WbMergeArray(private val dynRead: Boolean) extends Module {
  private val P = 3 // fflags write-back ports (fflagsWBs in the ROB)
  private val E = 352 // entries (RobSize)
  private val Q = 2 // enqueue ports (for isFirstEnq)
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
  private def win(x: UInt, off: Int, w: Int): UInt = (x >> off)(w - 1, 0)
  private val wbValid = io.in2(P - 1, 0)
  private val wbWflags = io.in3(P - 1, 0)
  private val wbIdx = Seq.tabulate(P)(p => (win(io.in0, p * 9, 9) ^ win(io.in1, p * 13, 9))(IW - 1, 0))
  private val wbFflags = Seq.tabulate(P)(p => win(io.in3, 26 + p * 5, 5))
  private val enqValid = io.in4(Q - 1, 0)
  private val enqIdx = Seq.tabulate(Q)(q => (win(io.ctrl, q * 7, 9) ^ win(io.in1, q * 17 + 5, 9))(IW - 1, 0))
  private val dynIdx = (win(io.in5, 40, 9) ^ win(io.ctrl, 32, 9))(IW - 1, 0) % E.U

  // ---- per-entry state columns
  private val entryValid = RegInit(VecInit(Seq.fill(E)(false.B)))
  private val fflagsReg = RegInit(VecInit(Seq.fill(E)(0.U(5.W))))

  for (e <- 0 until E) {
    // fflags family, exact Rob.scala:1066-1071 structure
    val fflagsCanWbSeq = Seq.tabulate(P)(p => wbValid(p) && wbIdx(p) === e.U && wbWflags(p))
    val fflagsRes = fflagsCanWbSeq.zip(wbFflags).map { case (c, f) => Mux(c, f, 0.U) }.fold(0.U)(_ | _)
    // isFirstEnq = !robEntries(i).valid && instCanEnqFlag (Rob.scala:1027-1037 shape)
    val enqMatch = enqValid.asBools.zip(enqIdx).map { case (v, x) => v && x === e.U }
    val isFirstEnq = !entryValid(e) && enqMatch.reduce(_ || _)
    when(isFirstEnq) {
      entryValid(e) := true.B
      fflagsReg(e) := 0.U
    }.elsewhen(fflagsRes.orR) {
      fflagsReg(e) := fflagsReg(e) | fflagsRes
    }
  }

  // ---- observable folds
  private val checksumReg = RegInit(0.U(64.W))
  private val validCnt = PopCount(entryValid)
  private val ffFold = fflagsReg.map(x => Cat(0.U(59.W), x)).reduce(_ ^ _)
  // dynamic-index read: keeps fflagsReg a single array node in gsim (dynRead arm)
  private val dynRd = if (dynRead) fflagsReg(dynIdx) else 0.U(5.W)
  io.out0 := ffFold ^ Cat(0.U(59.W), dynRd)
  io.out1 := validCnt
  io.out2 := 0.U
  io.out3 := 0.U
  io.flags := validCnt
  checksumReg := checksumReg ^ ffFold ^ Cat(0.U(59.W), dynRd) ^ validCnt
  io.checksum := checksumReg
}

class WbMergeArrayDyn extends WbMergeArray(dynRead = true)
class WbMergeArrayStatic extends WbMergeArray(dynRead = false)

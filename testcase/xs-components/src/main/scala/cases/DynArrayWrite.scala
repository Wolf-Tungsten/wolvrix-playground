package xscomponents

import chisel3._
import chisel3.util._

// Minimal reproduction of the XiangShan ROB debug-array dynamic write
// (testcase/xiangshan src/main/scala/xiangshan/backend/rob/Rob.scala:1513-1521):
//   val tab = RegInit(VecInit.fill(E)(VecInit.fill(L)(0.U)))
//   wbs.foreach { wb => when (wb.fire && validArr(wb.idx) && wb.wen) { tab(wb.idx)(wb.lane) := wb.data } }
// firtool unrolls this into per-entry static-enable writes; grhsim reg-to-mem
// then keeps 352-style per-row write ports instead of one dynamic port.
// Port convention follows tb/xs_component_bench.hpp: in0..in5/ctrl in,
// out0..out3/flags/checksum out.
class DynArrayWrite extends Module {
  private val E = 32 // entries (RobSize role)
  private val L = 8 // lanes (vdIdx role)
  private val P = 2 // write-back ports (vldWBs role)
  private val IW = 5 // log2Ceil(32)
  private val LW = 3 // log2Ceil(8)

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

  private def win(x: UInt, off: Int, w: Int): UInt = (x >> off)(w - 1, 0)
  private val wbFire = io.in2(P - 1, 0)
  private val wbWen = io.in3(P - 1, 0)
  private val wbIdx = Seq.tabulate(P)(p => (win(io.in0, p * 16, 16) ^ win(io.in1, p * 16, 16))(IW - 1, 0) % E.U)
  private val wbLane = Seq.tabulate(P)(p => win(io.in0, p * 16 + 8, 8)(LW - 1, 0))
  private val wbData = Seq.tabulate(P)(p => win(io.in4, p * 8, 8))
  private val enqFire = io.in5(0)
  private val enqIdx = win(io.in5, 8, 8)(IW - 1, 0) % E.U
  private val deqFire = io.in5(1)
  private val deqIdx = win(io.in5, 16, 8)(IW - 1, 0) % E.U
  private val dynIdx = win(io.ctrl, 0, 8)(IW - 1, 0) % E.U

  private val validArr = RegInit(VecInit(Seq.fill(E)(false.B)))
  private val tab = RegInit(VecInit(Seq.fill(E)(VecInit(Seq.fill(L)(0.U(8.W))))))

  when(enqFire) { validArr(enqIdx) := true.B }
  when(deqFire) { validArr(deqIdx) := false.B }

  // ROB shape: per-wb-port dynamic write guarded by a dynamic read of another array
  for (p <- 0 until P) {
    when(wbFire(p) && validArr(wbIdx(p)) && wbWen(p)) {
      tab(wbIdx(p))(wbLane(p)) := wbData(p)
    }
  }

  // dynamic readout + folds so everything stays live
  private val rd = tab(dynIdx).reduce(_ ^ _)
  private val validCnt = PopCount(validArr)
  private val checksumReg = RegInit(0.U(64.W))
  io.out0 := rd
  io.out1 := validCnt
  io.out2 := 0.U
  io.out3 := 0.U
  io.flags := validCnt
  checksumReg := checksumReg ^ Cat(0.U(56.W), rd) ^ validCnt
  io.checksum := checksumReg
}

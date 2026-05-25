package xscomponents

import chisel3._
import chisel3.util._

// Extracted from the banked StoreQueueData shape in
// xiangshan/mem/lsqueue/StoreQueueData.scala and the store-data forwarding
// selection path around StoreQueue.scala.
class XsStoreQueueBanksLarge extends XsComponentModule {
  import XsCommon._

  private val banks = 8
  private val rows = 32

  val data = RegInit(VecInit(Seq.fill(banks)(VecInit(Seq.fill(rows)(0.U(64.W))))))
  val mask = RegInit(VecInit(Seq.fill(banks)(VecInit(Seq.fill(rows)(0.U(8.W))))))
  val writeIdx0 = io.in0(7, 0)
  val writeIdx1 = io.in1(7, 0)
  val readIdx0 = io.in2(7, 0)
  val readIdx1 = io.in3(7, 0)
  val writeData0 = io.in4
  val writeData1 = io.in5
  val writeMask0 = io.ctrl(7, 0)
  val writeMask1 = io.ctrl(15, 8)
  val wen0 = io.ctrl(16)
  val wen1 = io.ctrl(17)

  def bankOf(idx: UInt): UInt = idx(2, 0)
  def rowOf(idx: UInt): UInt = idx(7, 3)
  def mergeBytes(oldData: UInt, newData: UInt, maskBits: UInt): UInt =
    VecInit((0 until 8).map(i => Mux(maskBits(i), newData(8 * i + 7, 8 * i), oldData(8 * i + 7, 8 * i)))).asUInt

  val read0 = data(bankOf(readIdx0))(rowOf(readIdx0))
  val read1 = data(bankOf(readIdx1))(rowOf(readIdx1))
  val readMask0 = mask(bankOf(readIdx0))(rowOf(readIdx0))
  val readMask1 = mask(bankOf(readIdx1))(rowOf(readIdx1))

  for (bank <- 0 until banks) {
    for (row <- 0 until rows) {
      val hit0 = wen0 && bankOf(writeIdx0) === bank.U && rowOf(writeIdx0) === row.U
      val hit1 = wen1 && bankOf(writeIdx1) === bank.U && rowOf(writeIdx1) === row.U
      when (hit0 && hit1) {
        val merged = mergeBytes(data(bank)(row), writeData0, writeMask0)
        data(bank)(row) := mergeBytes(merged, writeData1, writeMask1)
        mask(bank)(row) := mask(bank)(row) | writeMask0 | writeMask1
      }.elsewhen (hit0) {
        data(bank)(row) := mergeBytes(data(bank)(row), writeData0, writeMask0)
        mask(bank)(row) := mask(bank)(row) | writeMask0
      }.elsewhen (hit1) {
        data(bank)(row) := mergeBytes(data(bank)(row), writeData1, writeMask1)
        mask(bank)(row) := mask(bank)(row) | writeMask1
      }
    }
  }

  val forward0 = Mux(writeIdx0 === readIdx0 && wen0, mergeBytes(read0, writeData0, writeMask0), read0)
  val forward1 = Mux(writeIdx1 === readIdx1 && wen1, mergeBytes(read1, writeData1, writeMask1), read1)
  val bankHot = VecInit((0 until banks).map(i => bankOf(readIdx0) === i.U || bankOf(readIdx1) === i.U)).asUInt

  io.out0 := forward0
  io.out1 := forward1
  io.out2 := Cat(0.U(56.W), readMask0 ^ readMask1)
  io.out3 := Cat(0.U(56.W), bankHot)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}


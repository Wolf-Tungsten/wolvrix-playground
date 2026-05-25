package xscomponents

import chisel3._
import chisel3.util._

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

  io.out0 := mergedLo
  io.out1 := mergedHi
  io.out2 := forwardLo
  io.out3 := forwardHi
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}


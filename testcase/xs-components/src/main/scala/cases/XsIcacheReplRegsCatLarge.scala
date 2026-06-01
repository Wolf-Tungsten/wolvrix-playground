package xscomponents

import chisel3._
import chisel3.util._

// Source-level distributed-register form that explicitly rebuilds the register
// group as one packed word, matching the concat + dynamic-slice pattern emitted
// for Reg(Vec) in XsIcacheReplRegsLarge.sv.
class XsIcacheReplRegsCatLarge extends XsComponentModule {
  private val sets = 128
  private val ports = 4
  private val stateBits = 3

  val repl = Seq.fill(sets)(RegInit(0.U(stateBits.W)))

  val writeSet = VecInit((0 until ports).map(i => io.in0(7 * i + 6, 7 * i)))
  val readSetBase = io.in1(6, 0)
  val writeData = VecInit((0 until ports).map(i => io.in2(3 * i + 2, 3 * i)))
  val writeEn = io.in4(ports - 1, 0)

  val nextStates = Wire(Vec(sets, UInt(stateBits.W)))
  for (set <- 0 until sets) {
    var state = repl(set)
    for (port <- 0 until ports) {
      state = Mux(writeEn(port) && writeSet(port) === set.U, writeData(port), state)
    }
    nextStates(set) := state
    repl(set) := nextStates(set)
  }

  val packedNext = Cat((0 until sets).reverse.map(i => nextStates(i)))

  val packedNextVec = packedNext.asTypeOf(Vec(sets, UInt(stateBits.W)))

  def readPacked(index: UInt): UInt = {
    packedNextVec(index)
  }

  val read0 = readPacked(readSetBase)
  val read1 = readPacked(readSetBase + 11.U)
  val read2 = readPacked(readSetBase + 22.U)
  val read3 = readPacked(readSetBase + 33.U)

  val out0 = Cat(0.U(61.W), read0)
  val out1 = Cat(0.U(61.W), read1)
  val out2 = Cat(0.U(61.W), read2)
  val out3 = Cat(0.U(61.W), read3)

  io.out0 := out0
  io.out1 := out1
  io.out2 := out2
  io.out3 := out3
  io.flags := out0 ^ out1 ^ out2 ^ out3 ^ io.ctrl
  io.checksum := io.flags
}

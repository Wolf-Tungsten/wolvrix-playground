package xscomponents

import chisel3._
import chisel3.util._

// Isolates the ICache replacer register-file access shape from
// XsIcacheReplacerLarge: 128 x 3-bit state, four dynamic read ports, and four
// conditional write ports.
class XsIcacheReplRegsLarge extends XsComponentModule {
  private val sets = 128
  private val ports = 4
  private val stateBits = 3

  val repl = RegInit(VecInit(Seq.fill(sets)(0.U(stateBits.W))))

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
  }

  val readValues = Wire(Vec(ports, UInt(stateBits.W)))
  for (port <- 0 until ports) {
    readValues(port) := repl(readSetBase + (port * 11).U)
  }

  repl := nextStates

  val out0 = Cat(0.U(61.W), readValues(0))
  val out1 = Cat(0.U(61.W), readValues(1))
  val out2 = Cat(0.U(61.W), readValues(2))
  val out3 = Cat(0.U(61.W), readValues(3))

  io.out0 := out0
  io.out1 := out1
  io.out2 := out2
  io.out3 := out3
  io.flags := out0 ^ out1 ^ out2 ^ out3 ^ io.ctrl
  io.checksum := io.flags
}

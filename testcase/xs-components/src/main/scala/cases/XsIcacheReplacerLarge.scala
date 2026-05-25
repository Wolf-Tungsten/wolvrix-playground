package xscomponents

import chisel3._
import chisel3.util._

// Extracted from frontend/icache/ICacheReplacer.scala plus the set-PLRU
// replacement state shape used by utility/Replacement.scala.
class XsIcacheReplacerLarge extends XsComponentModule {
  import XsCommon._

  private val sets = 64
  private val ways = 4
  private val ports = 4
  private val stateBits = ways - 1

  val repl = RegInit(VecInit(Seq.fill(sets)(0.U(stateBits.W))))
  val touchSetBase = io.in0(5, 0)
  val victimSetBase = io.in1(5, 0)
  val wayMask = io.in2(ways - 1, 0)
  val validMask = io.in3(ways - 1, 0)
  val touchWays = VecInit((0 until ports).map(i => (io.ctrl(2 * i + 1, 2 * i) ^ i.U)(1, 0)))
  val touchEn = io.in4(ports - 1, 0) | io.ctrl(ports + 15, 16)
  val victimEn = io.ctrl(31, 28)

  def plruVictim(state: UInt): UInt = {
    val left = !state(0)
    Mux(left, Cat(0.U(1.W), !state(1)), Cat(1.U(1.W), !state(2)))
  }

  def plruNext(state: UInt, way: UInt): UInt = {
    Mux(way(1) === 0.U, Cat(state(2), 1.U(1.W), way(0)), Cat(0.U(1.W), way(0), state(1)))
  }

  val nextStates = Wire(Vec(sets, UInt(stateBits.W)))
  val victimWays = Wire(Vec(ports, UInt(2.W)))
  for (set <- 0 until sets) {
    var state = repl(set)
    for (port <- 0 until ports) {
      val idx = touchSetBase + (set ^ (port * 13)).U
      state = Mux(touchEn(port) && idx === set.U, plruNext(state, touchWays(port)), state)
    }
    nextStates(set) := state
  }

  for (port <- 0 until ports) {
    val set = victimSetBase + (port * 11).U
    val raw = plruVictim(repl(set))
    val candidateMask = wayMask & validMask
    val fallback = PriorityEncoder(candidateMask)
    victimWays(port) := Mux(candidateMask(raw), raw, fallback)
  }

  repl := nextStates

  val stateSample = VecInit((0 until 16).map(i => Cat(0.U(61.W), nextStates(i)))) .reduce(_ ^ _)
  val victimPacked = Cat(0.U(56.W), victimWays.asUInt)
  val touchPacked = Cat(0.U(56.W), touchWays.asUInt)
  val activeVictim = Cat(0.U(60.W), victimEn & victimWays.asUInt(3, 0))

  io.out0 := stateSample
  io.out1 := victimPacked
  io.out2 := touchPacked
  io.out3 := activeVictim
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

package xscomponents

import chisel3._
import chisel3.util._

// Standalone medium/large stateful extract shaped from real XiangShan source:
// - testcase/xiangshan/src/main/scala/xiangshan/mem/vector/VSegmentUnit.scala
// This file is intentionally self-contained: no local xs-components helper,
// base class, or shared case template is referenced.
class XsReal018VectorVsegmentunitLarge extends Module {
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

  private def rotl(x: UInt, n: Int): UInt = Cat(x(63 - n, 0), x(63, 64 - n))
  private def rotr(x: UInt, n: Int): UInt = Cat(x(n - 1, 0), x(63, n))
  private def mix64(a: UInt, b: UInt, salt: Int): UInt = {
    val x = a ^ rotl(b, (salt % 31) + 1) ^ (BigInt("9e3779b97f4a7c15", 16) + salt).U(64.W)
    val y = x + rotr(a ^ b, (salt % 17) + 1)
    y ^ rotl(y, (salt % 23) + 1)
  }
  private def fold(values: Seq[UInt]): UInt = {
    var acc = values.head
    for ((value, idx) <- values.tail.zipWithIndex) {
      acc = mix64(acc, value, idx + 1 + 312)
    }
    acc
  }

  private val entries = 96
  private val lanes = 6
  private val updateWays = 4
  private val tapCount = 16
  private val salt = 312

  val tags = RegInit(VecInit((0 until entries).map(i => (BigInt(i * 131 + salt) & ((BigInt(1) << 64) - 1)).U(64.W))))
  val data = RegInit(VecInit((0 until entries).map(i => (BigInt(i * 257 + salt * 17) & ((BigInt(1) << 64) - 1)).U(64.W))))
  val meta = RegInit(VecInit((0 until entries).map(i => (BigInt(i * 17 + salt * 31) & ((BigInt(1) << 64) - 1)).U(64.W))))
  val valid = RegInit(0.U(entries.W))

  val requestTag = mix64(io.in0, io.in1, salt)
  val requestData = mix64(io.in2, io.in3 ^ io.ctrl, salt + 1)
  val requestMask = mix64(io.in4, io.in5, salt + 2)

  val hitBits = Wire(Vec(entries, Bool()))
  val touchBits = Wire(Vec(entries, Bool()))
  val nextTags = Wire(Vec(entries, UInt(64.W)))
  val nextData = Wire(Vec(entries, UInt(64.W)))
  val nextMeta = Wire(Vec(entries, UInt(64.W)))

  for (i <- 0 until entries) {
    val laneSel = (0 until lanes).map(l => io.ctrl((i + l * 7 + salt) & 63)).reduce(_ ^ _)
    val updateSel = (0 until updateWays).map(w => io.in0((i + w * 11 + salt) & 63)).reduce(_ ^ _)
    val entryKey = (BigInt(i * 4099 + salt * 65537) & ((BigInt(1) << 64) - 1)).U(64.W)
    val tagProbe = mix64(tags(i), entryKey ^ requestTag, salt + i)
    val dataProbe = mix64(data(i), requestData ^ meta(i), salt + i + entries)
    hitBits(i) := valid(i) && tagProbe(7, 0) === requestTag(7, 0)
    touchBits(i) := laneSel || updateSel || hitBits(i)
    nextTags(i) := Mux(touchBits(i), tagProbe ^ requestMask, tags(i))
    nextData(i) := Mux(touchBits(i), dataProbe ^ requestData, data(i))
    nextMeta(i) := Mux(touchBits(i), mix64(meta(i), nextTags(i) ^ nextData(i), salt + i + 2 * entries), meta(i))
  }

  tags := nextTags
  data := nextData
  meta := nextMeta
  valid := Mux(io.ctrl(63), (valid | touchBits.asUInt) & ~UIntToOH(io.in5(log2Ceil(entries) - 1, 0), entries), valid | touchBits.asUInt)

  val tagSample = (0 until tapCount).map(t => tags((t * entries / tapCount + salt) % entries)).reduce(_ ^ _)
  val dataSample = (0 until tapCount).map(t => data((t * entries / tapCount + salt * 3) % entries)).reduce(_ ^ _)
  val metaSample = (0 until tapCount).map(t => meta((t * entries / tapCount + salt * 5) % entries)).reduce(_ ^ _)
  val hitWord = Cat(0.U((64 - entries.min(64)).W), hitBits.asUInt(entries.min(64) - 1, 0))
  val touchWord = Cat(0.U((64 - entries.min(64)).W), touchBits.asUInt(entries.min(64) - 1, 0))
  val validWord = Cat(0.U((64 - entries.min(64)).W), valid(entries.min(64) - 1, 0))

  io.out0 := mix64(tagSample, dataSample, salt + 3)
  io.out1 := mix64(metaSample, validWord, salt + 4)
  io.out2 := mix64(hitWord, touchWord, salt + 5)
  io.out3 := mix64(validWord ^ io.ctrl, tagSample ^ metaSample, salt + 6)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

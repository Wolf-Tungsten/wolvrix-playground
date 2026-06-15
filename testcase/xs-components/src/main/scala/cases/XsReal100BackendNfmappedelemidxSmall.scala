package xscomponents

import chisel3._
import chisel3.util._

// Standalone small combinational extract shaped from real XiangShan source:
// - testcase/xiangshan/src/main/scala/xiangshan/backend/VecExcpDataMergeModule.scala:NfMappedElemIdx
class XsReal100BackendNfmappedelemidxSmall extends Module {
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

  private val vlen = 128
  private val idxWidth = log2Ceil(vlen + 1)
  private val minElemLen = 8
  private val maxElemNumPerVreg = vlen / minElemLen

  private def rotl(x: UInt, n: Int): UInt = Cat(x(63 - n, 0), x(63, 64 - n))

  private val nf = (io.in0 ^ io.ctrl)(2, 0)
  private val eewOH = UIntToOH((io.in1 ^ (io.ctrl >> 3))(1, 0), 4)

  private val out = Wire(new Bundle {
    val idxRangeVec = Vec(8, new XsNfMappedElemIdxRange(idxWidth))
  })
  private val rangeTable = Wire(Vec(8, Vec(8, new XsNfMappedElemIdxRange(idxWidth))))
  private val shiftedRangeTable = Wire(Vec(8, Vec(8, new XsNfMappedElemIdxRange(idxWidth))))

  for (nfIdx <- 0 until 8) {
    for (vdIdx <- 0 until 8) {
      val nFields = nfIdx + 1
      val vrgIdx = vdIdx / nFields
      rangeTable(nfIdx)(vdIdx) := XsNfMappedElemIdxRange(idxWidth)(
        (maxElemNumPerVreg * vrgIdx).U,
        (maxElemNumPerVreg * (vrgIdx + 1)).U,
      )
      shiftedRangeTable(nfIdx)(vdIdx) := Mux1H(
        (0 until 4).map(i =>
          eewOH(i) -> XsNfMappedElemIdxRange(idxWidth)(
            rangeTable(nfIdx)(vdIdx).from >> i,
            rangeTable(nfIdx)(vdIdx).until >> i,
          )
        )
      )
    }
  }

  out.idxRangeVec := shiftedRangeTable(nf)
  dontTouch(out.idxRangeVec)

  private def pack8(values: Seq[UInt]): UInt = Cat(values.reverse)

  private val fromWord = pack8((0 until 8).map(i => out.idxRangeVec(i).from))
  private val untilWord = pack8((0 until 8).map(i => out.idxRangeVec(i).until))
  private val selectorWord = Cat(0.U(57.W), nf, eewOH)
  private val inputMix0 = io.in2 ^ rotl(io.in3, 7)
  private val inputMix1 = io.in4 + rotl(io.in5 ^ io.ctrl, 13)

  io.out0 := fromWord
  io.out1 := untilWord
  io.out2 := fromWord ^ selectorWord ^ inputMix0
  io.out3 := untilWord ^ selectorWord ^ inputMix1
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := io.flags ^ rotl(io.out0 + io.out2, 11) ^ rotl(io.out1 + io.out3, 23)
}

class XsNfMappedElemIdxRange(w: Int) extends Bundle {
  val from = UInt(w.W)
  val until = UInt(w.W)

  def apply(_from: Bits, _until: Bits): this.type = {
    this.from := _from
    this.until := _until
    this
  }
}

object XsNfMappedElemIdxRange {
  def apply(w: Int)(_from: Bits, _until: Bits): XsNfMappedElemIdxRange =
    Wire(new XsNfMappedElemIdxRange(w)).apply(_from, _until)
}

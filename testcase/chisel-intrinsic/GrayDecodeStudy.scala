package study.intrinsics

import chisel3._
import _root_.circt.stage.ChiselStage
import utility.{GrayToBinary, SimulationPrimitives}

import java.nio.file.{Files, Path, Paths}

/** Packed Gray-to-binary conversion with an elaboration-scoped intrinsic switch. */
class GrayDecodeStudy(width: Int, variant: String) extends RawModule {
  require(width > 0)
  override def desiredName = "GrayDecode" + variant

  val in = IO(Input(UInt(width.W)))
  val out = IO(Output(UInt(width.W)))
  out := GrayToBinary(in)
}

object GrayDecodeStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 3, "<width> <output> <firtool>")
    val width = args(0).toInt
    require(width > 0)
    val out = Paths.get(args(1))
    val firtool = args(2)
    Files.createDirectories(out)
    for ((variant, mode) <- Seq("A" -> "none", "B" -> "gray-decode")) {
      val destination = out.resolve(variant)
      Files.createDirectories(destination)
      SimulationPrimitives.withMode(mode, Some(destination.resolve("calls.json"))) {
        val stageArgs = Array("--firtool-binary-path", firtool)
        val fir = ChiselStage.emitCHIRRTL(new GrayDecodeStudy(width, variant), args = stageArgs)
        val sv = ChiselStage.emitSystemVerilog(
          new GrayDecodeStudy(width, variant),
          args = stageArgs,
          firtoolOpts = Array(
            "-O=release",
            "--disable-all-randomization",
            "--default-layer-specialization=enable",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"
          )
        )
        Files.writeString(destination.resolve(s"GrayDecode$variant.fir"), fir)
        Files.writeString(destination.resolve(s"GrayDecode$variant.sv"), sv)
      }
    }
  }
}

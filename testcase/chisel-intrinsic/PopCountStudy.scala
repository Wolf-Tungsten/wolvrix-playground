package study.intrinsics

import chisel3._
import chisel3.util.log2Ceil
import _root_.circt.stage.ChiselStage
import utility.{PopCount, SimulationPrimitives}

import java.nio.file.{Files, Path, Paths}

class PopCountStudy(width: Int, lanes: Boolean, variant: String) extends RawModule {
  require(width > 0)
  override def desiredName = "PopCount" + variant

  val packed = if (!lanes) Some(IO(Input(UInt(width.W)))) else None
  val distributed = if (lanes) Some(IO(Input(Vec(width, Bool())))) else None
  val result = IO(Output(UInt(log2Ceil(BigInt(width) + 1).W)))

  result := (if (lanes) PopCount(distributed.get) else PopCount(packed.get))
}

object PopCountStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4, "width layout output firtool")
    val width = args(0).toInt
    val lanes = args(1) == "lanes"
    val out = Paths.get(args(2))
    Files.createDirectories(out)
    val firtool = args(3)
    for ((variant, mode) <- Seq("A" -> "none", "B" -> "popcount")) {
      val destination = out.resolve(variant)
      Files.createDirectories(destination)
      SimulationPrimitives.withMode(mode, Some(destination.resolve("calls.json"))) {
        val sv = ChiselStage.emitSystemVerilog(
          new PopCountStudy(width, lanes, variant),
          args = Array("--firtool-binary-path", firtool),
          firtoolOpts = Array(
            "-O=release",
            "--disable-all-randomization",
            "--default-layer-specialization=enable",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"
          )
        )
        Files.writeString(destination.resolve(s"PopCount$variant.sv"), sv)
      }
    }
  }
}

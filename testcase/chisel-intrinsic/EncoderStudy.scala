package study.intrinsics

import chisel3._
import chisel3.util._
import utility.{PriorityEncoder, ParallelPriorityEncoder, PriorityEncoderWithFlag, PriorityEncoderDefault, SimulationPrimitives}
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

class EncoderStudy(width: Int, lanes: Boolean, variant: String) extends RawModule {
  override def desiredName = "Encoder" + variant
  val x = if (!lanes) Some(IO(Input(UInt(width.W)))) else None
  val bits = if (lanes) Some(IO(Input(Vec(width, Bool())))) else None
  val default = IO(Input(UInt(32.W)))
  val unused = IO(Input(UInt(8.W)))
  private val input = x.getOrElse(bits.get.asUInt)
  val index = IO(Output(UInt(math.max(1, log2Ceil(width)).W)))
  val parallel = IO(Output(chiselTypeOf(index)))
  val flagged = IO(Output(chiselTypeOf(index)))
  val valid = IO(Output(Bool()))
  val fallback = IO(Output(UInt(32.W)))
  index := (if (lanes) PriorityEncoder(bits.get) else PriorityEncoder(input))
  parallel := (if (lanes) ParallelPriorityEncoder(bits.get) else ParallelPriorityEncoder(input))
  private val pair = if (lanes) PriorityEncoderWithFlag(bits.get) else PriorityEncoderWithFlag(input)
  flagged := pair._1
  valid := pair._2
  fallback := (if (lanes) PriorityEncoderDefault(bits.get, default) else PriorityEncoderDefault(input.asBools, default))
  // Dead/CSE references are intentionally ordinary values, without dontTouch.
  private val dead = if (lanes) PriorityEncoder(bits.get) else PriorityEncoder(input)
}

object EncoderStudyMain {
  def main(args: Array[String]): Unit = {
    val width = args(0).toInt
    val lanes = args(1) == "lanes"
    val out = Paths.get(args(2)); Files.createDirectories(out)
    for ((variant, mode) <- Seq("A" -> "none", "B" -> "priority-encode")) {
      val destination = out.resolve(variant); Files.createDirectories(destination)
      SimulationPrimitives.withMode(mode, Some(destination.resolve("calls.json"))) {
        val sv = ChiselStage.emitSystemVerilog(new EncoderStudy(width, lanes, variant),
          args = Array("--firtool-binary-path", args(3)),
          firtoolOpts = Array("-O=release", "--disable-all-randomization",
            "--default-layer-specialization=enable", "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
        Files.writeString(destination.resolve(s"Encoder$variant.sv"), sv)
      }
    }
    // A second ordinary elaboration in the same JVM must not inherit B's mode.
    val again = ChiselStage.emitSystemVerilog(new EncoderStudy(width, lanes, "Reset"),
      args = Array("--firtool-binary-path", args(3)))
    require(!again.contains("wolvrix_ctz_"), "simulation mode leaked across elaboration")
  }
}

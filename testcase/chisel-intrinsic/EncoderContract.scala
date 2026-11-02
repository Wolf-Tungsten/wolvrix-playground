package study.intrinsics

import chisel3._
import _root_.circt.stage.ChiselStage
import utility.{PriorityEncoder, SimulationPrimitives}
import java.nio.file.{Files, Paths}

class ConditionalEncoder(variant: String) extends RawModule {
  override def desiredName = "Conditional" + variant
  val x = IO(Input(UInt(8.W)))
  val enable = IO(Input(Bool()))
  val y = IO(Output(UInt(3.W)))
  y := 5.U
  when(enable) { y := PriorityEncoder(x) }
}

object EncoderContractMain {
  def main(args: Array[String]): Unit = {
    val root = Paths.get(args(0)); Files.createDirectories(root)
    def emit(generator: => RawModule): String = ChiselStage.emitSystemVerilog(generator,
      args = Array("--firtool-binary-path", args(1)),
      firtoolOpts = Array("-O=release", "--disable-all-randomization",
        "--default-layer-specialization=enable"))
    for ((variant, mode) <- Seq("A" -> "none", "B" -> "priority-encode")) {
      SimulationPrimitives.withMode(mode) {
        Files.writeString(root.resolve(s"Conditional$variant.sv"), emit(new ConditionalEncoder(variant)))
        for (empty <- Seq(true, false)) {
          var rejected = false
          try {
            emit(new RawModule {
              val y = IO(Output(UInt(8.W)))
              y := (if (empty) PriorityEncoder(Seq.empty[Bool])
                    else PriorityEncoder(Wire(UInt())))
            })
          } catch { case _: Exception => rejected = true }
          require(rejected, s"$mode accepted ${if (empty) "empty" else "unknown-width"} input")
        }
      }
    }
    val reset = emit(new ConditionalEncoder("Reset"))
    require(!reset.contains("wolvrix_ctz_"), "failed elaboration leaked simulation mode")
    Files.writeString(root.resolve("PASS.txt"), "both modes reject empty/unknown widths; scope restored after failure\n")
  }
}

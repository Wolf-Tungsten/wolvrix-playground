package study.vectorint

import chisel3._
import _root_.circt.stage.ChiselStage
import utility.{HostOpSpec, SimulationModels}
import yunsuan.vector.VectorALU.{VIAluFixComputeCarrier, VIAluFixPoint, VIAluFixPointInput}
import java.nio.file.{Files, Paths}

class VectorIntBehaviorFixture(model: String, behavior: Boolean, grouped: Boolean) extends Module {
  private val inWidth = new yunsuan.vector.VectorALU.VIAluFixPointInput(64).getWidth
  val io = IO(new Bundle { val in = Input(UInt(inWidth.W)); val out = Output(UInt(112.W)) })
  if (behavior) {
    val carrier = Module(new VIAluFixComputeCarrier(model))
    carrier.io.in := io.in
    io.out := carrier.io.out
    SimulationModels.functionalPipeline(model, carrier, 0, "", Seq((8,8),(16,16),(32,32),(64,64)),
      if (grouped) Some(carrier) else None,
      if (model.endsWith("lane")) "lane-core" else "whole-unit",
      Seq(HostOpSpec("lane-add-sub", Seq(64,64), 64, laneWidth = 8),
        HostOpSpec("lane-compare", Seq(64,64), 64, laneWidth = 8)))
  } else {
    require(!grouped, "hardware vector fixture cannot use grouped compute lowering")
    val point = Module(new VIAluFixPoint(64))
    point.io.in := io.in.asTypeOf(new VIAluFixPointInput(64))
    io.out := point.io.out.asUInt
  }
}

object VectorIntBehaviorStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4 || args.length == 5,
      "<output> <firtool> <model> <ordinary|grouped> or <output> <firtool> <model> <hardware|behavior> <ordinary|grouped>")
    val out = Paths.get(args(0)); Files.createDirectories(out)
    val behavior = if (args.length == 4) true else args(3) == "behavior"
    val grouped = if (args.length == 4) args(3) == "grouped" else args(4) == "grouped"
    require(!grouped || behavior, "hardware vector fixture cannot use grouped compute lowering")
    SimulationModels.withMode(if (behavior) args(2) else "hardware", Some(out.resolve("simulation_models.json")),
      computeLowering = if (grouped) "grouped" else "ordinary") {
      val sv = ChiselStage.emitSystemVerilog(new VectorIntBehaviorFixture(args(2), behavior, grouped),
        args = Array("--firtool-binary-path", args(1)),
        firtoolOpts = Array("-O=release", "--disable-all-randomization", "--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      Files.writeString(out.resolve("VectorIntBehavior.sv"), sv)
    }
  }
}

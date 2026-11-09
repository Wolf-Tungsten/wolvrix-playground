package study.vectorpu

import chisel3._
import _root_.circt.stage.ChiselStage
import utility.{HostOpSpec, SimulationModels}
import yunsuan.vector.{VIFuInput, VIFuOutput}
import yunsuan.vector.VectorALU.VIPUComputeCarrier
import java.nio.file.{Files, Paths}

class VectorPuBehaviorFixture(model: String, grouped: Boolean) extends Module {
  private val inWidth = new VIFuInput().getWidth
  private val outWidth = new VIFuOutput().getWidth
  val io = IO(new Bundle {
    val in = Input(UInt(inWidth.W))
    val out = Output(UInt(outWidth.W))
  })

  val carrier = Module(new VIPUComputeCarrier(model))
  carrier.io.in := io.in
  io.out := carrier.io.out
  SimulationModels.functionalPipeline(
    model,
    carrier,
    0,
    "",
    Seq((8, 8), (16, 16), (32, 32), (64, 64)),
    if (grouped) Some(carrier) else None,
    if (model.endsWith("lane")) "lane-core" else "whole-unit",
    Seq(
      HostOpSpec("vcpop", Seq(128), 64, laneWidth = 1),
      HostOpSpec("vfirst", Seq(128), 64, laneWidth = 1),
      HostOpSpec("vmsbf", Seq(128), 128, laneWidth = 1),
      HostOpSpec("vmsif", Seq(128), 128, laneWidth = 1),
      HostOpSpec("vmsof", Seq(128), 128, laneWidth = 1),
      HostOpSpec("viota", Seq(128), 128, laneWidth = 8),
      HostOpSpec("vid", Seq(128), 128, laneWidth = 8),
      HostOpSpec("vmvxs", Seq(128), 64, laneWidth = 64)
    )
  )
}

object VectorPuBehaviorStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4, "<output> <firtool> <model> <ordinary|grouped>")
    val out = Paths.get(args(0)); Files.createDirectories(out)
    val grouped = args(3) == "grouped"
    SimulationModels.withMode(args(2), Some(out.resolve("simulation_models.json")),
      computeLowering = if (grouped) "grouped" else "ordinary") {
      val sv = ChiselStage.emitSystemVerilog(
        new VectorPuBehaviorFixture(args(2), grouped),
        args = Array("--firtool-binary-path", args(1)),
        firtoolOpts = Array(
          "-O=release", "--disable-all-randomization",
          "--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      Files.writeString(out.resolve("VectorPuBehavior.sv"), sv)
    }
  }
}

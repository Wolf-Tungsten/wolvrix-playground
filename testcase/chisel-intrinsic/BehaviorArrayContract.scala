package study.models

import chisel3._
import _root_.circt.stage.ChiselStage
import utility.SimulationModels
import java.nio.file.{Files, Paths}

/** Contract test, separate from the deliberately two-update authoring example. */
class BehaviorArrayContract extends Module {
  val io = IO(new Bundle {
    val valid = Input(Vec(3, Bool()))
    val index = Input(Vec(3, UInt(5.W)))
    val value = Input(Vec(3, UInt(64.W)))
    val readIndex = Input(UInt(5.W))
    val state = Output(Vec(32, UInt(64.W)))
    val readValue = Output(UInt(64.W))
    val priorRead = Output(UInt(64.W))
    val copied = Output(UInt(64.W))
  })
  SimulationModels.model("commit-rat", clock, reset, commitBoundary="valid", updateGroup="array-contract") { model =>
    model.input("valid", io.valid); model.input("index", io.index); model.input("value", io.value)
    val state = model.array("state", 32, (row: Int) => row.U(64.W))
    val prior = model.array("prior", 1, 0.U(64.W))
    (0 until 3).foreach(lane => state.update(io.valid(lane), io.index(lane), io.value(lane)))
    prior.update(true.B, 0.U, state.read(io.readIndex))
    val copy = state.snapshot
    copy(0) := 123.U
    io.copied := copy(0)
    io.state := state.snapshot
    io.readValue := state.read(io.readIndex)
    io.priorRead := prior.read(0.U)
    model.output("state", io.state); model.check("prior", io.priorRead)
  }
}
object BehaviorArrayContractMain {
  def main(args: Array[String]): Unit = {
    val out=Paths.get(args(0)); Files.createDirectories(out)
    SimulationModels.withMode("commit-rat", Some(out.resolve("simulation_models.json"))) {
      val sv=ChiselStage.emitSystemVerilog(new BehaviorArrayContract,
        args=Array("--firtool-binary-path", args(1)),
        firtoolOpts=Array("-O=release", "--disable-all-randomization", "--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      Files.writeString(out.resolve("BehaviorArrayContract.sv"),sv)
    }
  }
}

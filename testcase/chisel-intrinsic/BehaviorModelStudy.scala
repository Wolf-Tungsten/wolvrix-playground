package study.models

import chisel3._
import circt.stage.ChiselStage
import utility.SimulationModels

import java.nio.file.{Files, Paths}

/**
  * A compact commit/RAT observer model.  The hardware and behavior variants
  * have identical ports and state semantics; only the state construction API
  * changes during elaboration.
  */
class CommitRatBehaviorStudy(useBehavior: Boolean) extends Module {
  val io = IO(new Bundle {
    val commitValid = Input(Bool())
    val commitDest = Input(UInt(5.W))
    val commitData = Input(UInt(64.W))
    val ratValid = Input(Bool())
    val ratDest = Input(UInt(5.W))
    val ratPhy = Input(UInt(6.W))
    val arch = Output(Vec(32, UInt(64.W)))
    val rat = Output(Vec(32, UInt(6.W)))
  })

  val archState = Wire(Vec(32, UInt(64.W)))
  val ratState = Wire(Vec(32, UInt(6.W)))

  if (useBehavior) {
    require(SimulationModels.enabled("commit-rat"),
      "behavior fixture requires the commit-rat simulation model mode")
    SimulationModels.model(
      "commit-rat",
      clock,
      reset,
      observerOnly = true,
      commitBoundary = "commitValid",
      updateGroup = "commit-rat",
    ) { ctx =>
      val commitValid = ctx.input("commit.valid", io.commitValid)
      val commitDest = ctx.input("commit.dest", io.commitDest)
      val commitData = ctx.input("commit.data", io.commitData)
      val ratValid = ctx.input("rat.valid", io.ratValid)
      val ratDest = ctx.input("rat.dest", io.ratDest)
      val ratPhy = ctx.input("rat.phy", io.ratPhy)

      val archRegs = (0 until 32).map(i => ctx.register(s"arch.x$i", 0.U(64.W)))
      val ratRegs = (0 until 32).map(i => ctx.register(s"rat.x$i", 0.U(6.W)))

      archRegs.zipWithIndex.foreach { case (state, index) =>
        val hit = commitValid && commitDest === index.U
        state.update(hit, Mux(hit, commitData, state.read))
        archState(index) := state.read
      }
      ratRegs.zipWithIndex.foreach { case (state, index) =>
        val hit = ratValid && ratDest === index.U
        state.update(hit, Mux(hit, ratPhy, state.read))
        ratState(index) := state.read
      }

      ctx.output("arch.state", VecInit(archRegs.map(_.read)).asUInt)
      ctx.output("rat.state", VecInit(ratRegs.map(_.read)).asUInt)
    }
  } else {
    val archRegs = RegInit(VecInit(Seq.fill(32)(0.U(64.W))))
    val ratRegs = RegInit(VecInit(Seq.fill(32)(0.U(6.W))))
    when(io.commitValid) {
      archRegs(io.commitDest) := io.commitData
    }
    when(io.ratValid) {
      ratRegs(io.ratDest) := io.ratPhy
    }
    archState := archRegs
    ratState := ratRegs
  }

  io.arch := archState
  io.rat := ratState
}

object BehaviorModelStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 2, "<output> <firtool>")
    val out = Paths.get(args(0))
    val firtool = args(1)
    Files.createDirectories(out)
    for ((variant, useBehavior, mode) <- Seq(
      ("A", false, "hardware"),
      ("B", true, "commit-rat"),
    )) {
      val destination = out.resolve(variant)
      Files.createDirectories(destination)
      SimulationModels.withMode(mode, Some(destination.resolve("simulation_models.json"))) {
        val stageArgs = Array("--firtool-binary-path", firtool)
        val sv = ChiselStage.emitSystemVerilog(
          new CommitRatBehaviorStudy(useBehavior),
          args = stageArgs,
          firtoolOpts = Array(
            "-O=release",
            "--disable-all-randomization",
            "--default-layer-specialization=enable",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"
          )
        )
        Files.writeString(destination.resolve(s"CommitRatBehavior$variant.sv"), sv)
      }
    }
  }
}

package study.multiply

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import utility.{HostOpSpec, SimulationModels}
import yunsuan.MULOpType
import yunsuan.util.GatedValidRegNext

/** The same packed stimulus/observation interface for all arithmetic families. */
class MultiplyFixture(kind: String, behavior: Boolean, computeGrouped: Boolean = false) extends Module {
  val io = IO(new Bundle {
    val valid = Input(Bool())
    val a, b, c = Input(UInt(64.W))
    val op = Input(UInt(5.W))
    val format = Input(UInt(2.W))
    val rm = Input(UInt(3.W))
    val signedA, signedB, signedC = Input(Bool())
    val high, macc, sub, widen, fixed, uop = Input(Bool())
    val canonical = Input(UInt(3.W))
    val result = Output(UInt(64.W))
    val flags = Output(UInt(20.W))
    val outValid = Output(Bool())
  })
  val stages = if (kind.contains("fp")) 3 else 2
  var valid = io.valid
  for (_ <- 0 until stages) valid = GatedValidRegNext(valid)
  io.outValid := valid
  io.flags := 0.U
  kind match {
    case "int-mul" =>
      val dut = Module(new yunsuan.scalar.Mul(64, behavior, computeGrouped))
      dut.io.in.valid := io.valid
      dut.io.in.bits.fuOpType := io.op
      dut.io.in.bits.src(0) := Mux(MULOpType.isMulw7(io.op), io.a(6, 0), io.a)
      dut.io.in.bits.src(1) := io.b
      io.result := dut.io.out
      SimulationModels.functionalPipeline(kind, dut, stages, "io_in_valid", Seq((64, 64)), dut.simulationComputeCarrier)
    case "vec-int-mul" | "vec-int-mac-lane" | "vec-int-mac-whole" =>
      val macModel = if (kind == "vec-int-mac-lane" || kind == "vec-int-mac-whole") kind else "vec-int-mac-lane"
      val dut = Module(new yunsuan.vector.mac.VIMac64b(behavior, computeGrouped, macModel))
      dut.io.fire := io.valid
      dut.io.info := 0.U.asTypeOf(dut.io.info)
      dut.io.info.uopIdx := io.uop
      dut.io.info.vxrm := io.rm(1, 0)
      dut.io.srcType(0) := Cat(0.U(1.W), io.signedA, io.format)
      dut.io.srcType(1) := Cat(0.U(1.W), io.signedB, io.format)
      dut.io.vdType := Cat(0.U(1.W), io.signedC, io.format + io.widen)
      dut.io.vs2 := io.a
      dut.io.vs1 := io.b
      dut.io.oldVd := io.c
      dut.io.highHalf := io.high
      dut.io.isMacc := io.macc
      dut.io.isSub := io.sub
      dut.io.widen := io.widen
      dut.io.isFixP := io.fixed
      io.result := dut.io.vd
      io.flags := dut.io.vxsat
      SimulationModels.functionalPipeline(kind, dut, stages, "io_fire", Seq((8,8),(16,16),(32,32),(64,64)), dut.simulationComputeCarrier,
        if (kind == "vec-int-mac-lane") "lane-core" else if (kind == "vec-int-mac-whole") "whole-unit" else "none",
        Seq(HostOpSpec("lane-mul", Seq(64,64), 128, laneWidth = 8), HostOpSpec("lane-merge", Seq(64), 64, laneWidth = 8)))
    case "fp-mul" =>
      val dut = Module(new yunsuan.fpu.FloatFMA(behavior, computeGrouped))
      dut.io.fire := io.valid
      dut.io.fp_a := io.a; dut.io.fp_b := io.b; dut.io.fp_c := io.c
      dut.io.fp_format := io.format; dut.io.round_mode := io.rm; dut.io.op_code := io.op
      dut.io.fp_aIsFpCanonicalNAN := io.canonical(0)
      dut.io.fp_bIsFpCanonicalNAN := io.canonical(1)
      dut.io.fp_cIsFpCanonicalNAN := io.canonical(2)
      io.result := dut.io.fp_result; io.flags := dut.io.fflags
      SimulationModels.functionalPipeline(kind, dut, stages, "io_fire", Seq((53,53),(24,24),(11,11)), dut.simulationComputeCarrier)
    case "vec-fp-mul" =>
      val dut = Module(new yunsuan.vector.VectorFloatFMA(behavior, computeGrouped))
      dut.io.fire := io.valid
      dut.io.fp_a := io.a; dut.io.fp_b := io.b; dut.io.fp_c := io.c
      dut.io.widen_a := io.a; dut.io.widen_b := io.b
      dut.io.fp_format := io.format; dut.io.round_mode := io.rm; dut.io.op_code := io.op
      dut.io.uop_idx := io.uop; dut.io.res_widening := io.widen
      dut.io.frs1 := 0.U; dut.io.is_vec := true.B; dut.io.is_frs1 := false.B
      dut.io.fp_aIsFpCanonicalNAN := io.canonical(0)
      dut.io.fp_bIsFpCanonicalNAN := io.canonical(1)
      dut.io.fp_cIsFpCanonicalNAN := io.canonical(2)
      io.result := dut.io.fp_result; io.flags := dut.io.fflags
      SimulationModels.functionalPipeline(kind, dut, stages, "io_fire", Seq((53,53),(24,24),(11,11)), dut.simulationComputeCarrier)
    case _ => throw new IllegalArgumentException(kind)
  }
}

object MultiplyBehaviorStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4 || args.length == 5, "<output> <firtool> <kind> <hardware|behavior> [ordinary|grouped]")
    val out = Paths.get(args(0)); Files.createDirectories(out)
    val kind = args(2); val behavior = args(3) == "behavior"
    val computeGrouped = args.lift(4).contains("grouped")
    SimulationModels.withMode(if (behavior) kind else "hardware", Some(out.resolve("simulation_models.json")),
      computeLowering = if (computeGrouped) "grouped" else "ordinary") {
      val sv = ChiselStage.emitSystemVerilog(new MultiplyFixture(kind, behavior, computeGrouped),
        args = Array("--firtool-binary-path", args(1)),
        firtoolOpts = Array("-O=release", "--disable-all-randomization", "--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      Files.writeString(out.resolve("MultiplyFixture.sv"), sv)
    }
  }
}

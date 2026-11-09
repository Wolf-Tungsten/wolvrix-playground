package study.integer

import chisel3._
import _root_.circt.stage.ChiselStage
import org.chipsalliance.cde.config.Parameters
import utility.{HostOpSpec, LogUtilsOptionsKey, LogUtilsOptions, SimulationModels}
import xiangshan.{FuOpType, XSCoreParamsKey, XSCoreParameters, XSModule}
import xiangshan.backend.fu.{AluDataModule, ClmulModule, CountModule, IntAluComputeCarrier, IntBkuComputeCarrier, MiscModule}
import top.TLConfig

/** Small scalar carrier fixture used to validate ordinary/grouped lowering. */
class IntegerBehaviorFixture(model: String, behavior: Boolean, grouped: Boolean)(implicit p: Parameters) extends XSModule {
  val io = IO(new Bundle {
    val in = Input(UInt(if (model == "int-alu") 201.W else 134.W))
    val out = Output(UInt(64.W))
  })
  model match {
    case "int-alu" =>
      if (behavior) {
        val carrier = Module(new IntAluComputeCarrier(aluNeedPc = true))
        carrier.io.in := io.in
        io.out := carrier.io.out
        SimulationModels.functionalPipeline(
          model, carrier, 0, "", Seq((64, 64)), if (grouped) Some(carrier) else None,
          computeOps = Seq(
            HostOpSpec("add-sub", Seq(64, 64), 64), HostOpSpec("compare", Seq(64, 64), 64),
            HostOpSpec("shift-rotate", Seq(64, 64), 64, shiftMask = 63),
            HostOpSpec("bitmanip", Seq(64, 64), 64), HostOpSpec("misc", Seq(64, 64), 64)))
      } else {
        require(!grouped, "hardware integer fixture cannot use grouped compute lowering")
        val core = Module(new AluDataModule(aluNeedPc = true))
        core.io.src(0) := io.in(63, 0)
        core.io.src(1) := io.in(127, 64)
        core.io.func := io.in(136, 128).asTypeOf(FuOpType())
        core.io.pc := io.in(200, 137)
        io.out := core.io.result
      }
    case "int-bku" =>
      if (behavior) {
        val carrier = Module(new IntBkuComputeCarrier)
        carrier.io.in := io.in
        io.out := carrier.io.out
        SimulationModels.functionalPipeline(
          model, carrier, 2, "", Seq((64, 64)), if (grouped) Some(carrier) else None,
          computeOps = Seq(
            HostOpSpec("clz-ctz-cpop", Seq(64), 64),
            HostOpSpec("clmul", Seq(64, 64), 128, implementation = "fallback"),
            HostOpSpec("xperm", Seq(64, 64), 64, implementation = "fallback")))
      } else {
        require(!grouped, "hardware integer fixture cannot use grouped compute lowering")
        val count = Module(new CountModule)
        val clmul = Module(new ClmulModule)
        val misc = Module(new MiscModule)
        count.io.src := io.in(63, 0)
        count.io.func := io.in(133, 128)
        count.io.regEnable := true.B
        clmul.io.src(0) := io.in(63, 0)
        clmul.io.src(1) := io.in(127, 64)
        clmul.io.func := io.in(133, 128)
        clmul.io.regEnable := true.B
        misc.io.src(0) := io.in(63, 0)
        misc.io.src(1) := io.in(127, 64)
        misc.io.func := io.in(133, 128)
        misc.io.regEnable := true.B
        io.out := Mux(io.in(131), count.io.out, Mux(io.in(130), misc.io.out, clmul.io.out))
      }
    case other => throw new IllegalArgumentException(other)
  }
}

object IntegerBehaviorStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4 || args.length == 5,
      "<output> <firtool> <int-alu|int-bku> <ordinary|grouped> or <output> <firtool> <model> <hardware|behavior> <ordinary|grouped>")
    val out = java.nio.file.Paths.get(args(0)); java.nio.file.Files.createDirectories(out)
    val model = args(2)
    val behavior = if (args.length == 4) true else args(3) == "behavior"
    val grouped = if (args.length == 4) args(3) == "grouped" else args(4) == "grouped"
    require(!grouped || behavior, "hardware integer fixture cannot use grouped compute lowering")
    implicit val p: Parameters = (new TLConfig).alterPartial {
      case XSCoreParamsKey => XSCoreParameters()
      case LogUtilsOptionsKey => LogUtilsOptions(false, false, false)
    }
    SimulationModels.withMode(if (behavior) model else "hardware", Some(out.resolve("simulation_models.json")),
      computeLowering = if (grouped) "grouped" else "ordinary") {
      val sv = ChiselStage.emitSystemVerilog(new IntegerBehaviorFixture(model, behavior, grouped),
        args = Array("--firtool-binary-path", args(1)),
        firtoolOpts = Array("-O=release", "--disable-all-randomization", "--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      java.nio.file.Files.writeString(out.resolve("IntegerBehavior.sv"), sv)
    }
  }
}

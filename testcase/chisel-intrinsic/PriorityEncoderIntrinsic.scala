// Emission-only experiment: no DPI implementation or simulator is built here.
package study.intrinsics

import chisel3._
import chisel3.experimental.{IntParam, StringParam}
import chisel3.util.PriorityEncoder
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

/** Index of the least-significant set bit; zero input returns 64.
  * The 7-bit result is combinational in both elaboration modes.
  */
class PriorityEncoderIntrinsic(
  useIntrinsic: Boolean,
  probeCustomName: Boolean = false
) extends RawModule {
  override def desiredName = "PriorityEncoder64"
  val in = IO(Input(UInt(64.W)))
  val index = IO(Output(UInt(7.W)))

  if (!useIntrinsic) {
    index := Mux(in.orR, PriorityEncoder(in), 64.U(7.W))
  } else if (probeCustomName) {
    // Diagnostic only: does the unmodified firtool recognize our semantic name?
    index := IntrinsicExpr(
      "wolvrix_ctz64_or64", UInt(7.W),
      "inputWidth" -> IntParam(64), "zeroResult" -> IntParam(64)
    )(in)
  } else {
    // Existing CIRCT lowering for a combinational external function call.
    // Its implementation is deliberately outside this emission experiment.
    // DPI scalar returns use a native ABI width; the module keeps its 7-bit port.
    val encoded = IntrinsicExpr(
      "circt_dpi_call", UInt(32.W),
      "functionName" -> StringParam("wolvrix_ctz64_or64"),
      "isClocked" -> IntParam(0),
      "inputNames" -> StringParam("value"),
      "outputName" -> StringParam("index")
    )(true.B, in)
    index := encoded(6, 0)
  }
}

object PriorityEncoderIntrinsicMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4, "<useIntrinsic:true|false> <output> <firtool> <dpi|custom>")
    require(Set("true", "false").contains(args(0)))
    require(Set("dpi", "custom").contains(args(3)))
    val useIntrinsic = args(0).toBoolean
    val probeCustomName = args(3) == "custom"
    val destination = Paths.get(args(1))
    Files.createDirectories(destination)
    val stageArgs = Array("--firtool-binary-path", args(2))
    def design = new PriorityEncoderIntrinsic(useIntrinsic, probeCustomName)
    // Retain the semantic expression even when firtool rejects an unknown name.
    Files.writeString(destination.resolve("PriorityEncoder64.fir"),
      ChiselStage.emitCHIRRTL(design, args = stageArgs))
    val verilog = ChiselStage.emitSystemVerilog(design, args = stageArgs,
      firtoolOpts = Array("-O=release", "--disable-all-randomization",
        "--default-layer-specialization=enable",
        "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
    Files.writeString(destination.resolve("PriorityEncoder64.sv"), verilog)
  }
}

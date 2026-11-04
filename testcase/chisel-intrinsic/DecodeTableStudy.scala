package study.intrinsics

import chisel3._
import chisel3.util.BitPat
import chisel3.util.experimental.decode.{QMCMinimizer, EspressoMinimizer, TruthTable}
import _root_.circt.stage.ChiselStage
import utility.{ListLookup, DecodeLogic, decoder, SimulationPrimitives}
import java.nio.file.{Files, Paths}

/** Replays captured raw tables through the original API and the intrinsic API. */
class DecodeTableStudy(payload: String, espresso: Boolean) extends RawModule {
  override def desiredName = "DecodeTableStudy"
  private val p = payload.split("\\|",-1)
  private val n = p(2).toInt
  private val m = p(3).toInt
  private val widths = p(4).split(",").map(_.toInt).toSeq
  private val rows = if (p(7).isEmpty) Seq.empty else p(7).split(";").toSeq.map(_.split(",").map(BigInt(_,16)))
  private def pattern(value: BigInt, mask: BigInt, width: Int): BitPat =
    BitPat("b" + (0 until width).reverse.map(i => if (!mask.testBit(i)) '?' else if (value.testBit(i)) '1' else '0').mkString)
  private def fields(value: BigInt): List[UInt] = {
    var high=m
    widths.map { w => high-=w; ((value>>high)&((BigInt(1)<<w)-1)).U(w.W) }.toList
  }
  private def bitFields(value: BigInt, mask: BigInt): Seq[BitPat] = {
    var high=m
    widths.map { w =>
      high-=w
      val bits=(BigInt(1)<<w)-1
      pattern((value>>high)&bits,(mask>>high)&bits,w)
    }
  }
  val in = IO(Input(UInt(n.W)))
  val out = IO(Output(UInt(m.W)))
  if (p(1)=="P") {
    val result=ListLookup(in,fields(BigInt(p(5),16)),rows.map(r => pattern(r(1),r(0),n) -> fields(r(2))).toArray)
    out := chisel3.util.Cat(result)
  } else if (widths.size > 1) {
    out := chisel3.util.Cat(DecodeLogic(in,bitFields(BigInt(p(5),16),BigInt(p(6),16)),
      rows.map(r => pattern(r(1),r(0),n) -> bitFields(r(2),r(3))),
      if(espresso) EspressoMinimizer else QMCMinimizer))
  } else {
    out := decoder(if(espresso) EspressoMinimizer else QMCMinimizer, in,
      TruthTable(rows.map(r => pattern(r(1),r(0),n) -> pattern(r(2),r(3),m)),
        pattern(BigInt(p(5),16),BigInt(p(6),16),m)))
  }
}

object DecodeTableStudyMain {
  def main(args: Array[String]): Unit = {
    require(args.length == 4, "<payload-file> <output> <firtool> <qmc|espresso>")
    val payload=Files.readString(Paths.get(args(0))).trim
    val root=Paths.get(args(1));Files.createDirectories(root)
    for((variant,mode)<-Seq("A"->"none","B"->"decode-table")) {
      val out=root.resolve(variant);Files.createDirectories(out)
      SimulationPrimitives.withMode(mode,Some(out.resolve("calls.json"))) {
        val sv=ChiselStage.emitSystemVerilog(new DecodeTableStudy(payload,args(3)=="espresso"),
          args=Array("--firtool-binary-path",args(2)),
          firtoolOpts=Array("-O=release","--disable-all-randomization","--default-layer-specialization=enable",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
        Files.writeString(out.resolve("DecodeTableStudy.sv"),sv)
      }
    }
  }
}

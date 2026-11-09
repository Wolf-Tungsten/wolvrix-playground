package study.multiply

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import org.chipsalliance.cde.config.Parameters
import java.nio.file.{Files, Paths}
import utility.SimulationModels
import xiangshan._
import xiangshan.backend.fu._
import yunsuan.{MULOpType, VimacType, VfmaType}

/** Original FU control and architectural vector merge around both datapaths. */
class MultiplyWrapperFixture(kind: String)(implicit p: Parameters) extends XSModule {
  val io = IO(new Bundle {
    val valid, ready, flush = Input(Bool())
    val a, b, c, mask = Input(UInt(128.W))
    val op = Input(UInt(5.W))
    val format = Input(UInt(2.W))
    val rm = Input(UInt(3.W))
    val vl, vstart, tag = Input(UInt(8.W))
    val uop = Input(UInt(3.W))
    val vm, ma, ta = Input(Bool())
    val equal, outValid = Output(Bool())
    val result = Output(UInt(128.W))
    val flags = Output(UInt(6.W))
  })
  val cfg = kind match {
    case "int-mul" => FuConfig.MulCfg
    case "fp-mul" => FuConfig.FmacCfg
    case "vec-int-mul" => FuConfig.VimacCfg
    case "vec-fp-mul" => FuConfig.VfmaCfg
  }
  val ops = kind match {
    case "int-mul" => Seq(MULOpType.mul,MULOpType.mulh,MULOpType.mulhsu,MULOpType.mulhu,MULOpType.mulw,MULOpType.mulw7)
    case "fp-mul" => Seq(VfmaType.vfmul,VfmaType.vfmacc,VfmaType.vfnmacc,VfmaType.vfmsac,VfmaType.vfnmsac)
    case "vec-fp-mul" => Seq(VfmaType.vfmul,VfmaType.vfmacc,VfmaType.vfnmacc,VfmaType.vfmsac,VfmaType.vfnmsac,
      VfmaType.vfmadd,VfmaType.vfnmadd,VfmaType.vfmsub,VfmaType.vfnmsub,VfmaType.vfmul_w,VfmaType.vfmacc_w)
    case "vec-int-mul" => Seq(VimacType.vmul,VimacType.vmulh,VimacType.vmulhu,VimacType.vmulhsu,VimacType.vwmul,
      VimacType.vwmulu,VimacType.vwmulsu,VimacType.vmacc,VimacType.vwmacc,VimacType.vwmaccu,VimacType.vwmaccsu,
      VimacType.vwmaccus,VimacType.vnmsac,VimacType.vmadd,VimacType.vnmsub,VimacType.vsmul)
  }
  val hardware = SimulationModels.withMode("hardware") { cfg.fuGen(p,cfg) }
  val behavior = SimulationModels.withMode(kind) { cfg.fuGen(p,cfg) }
  val ctrl = Wire(new FuncUnitCtrlInput(cfg));ctrl := 0.U.asTypeOf(ctrl)
  ctrl.fuOpType := VecInit(ops)(io.op)
  ctrl.robIdx.value := io.tag
  ctrl.pdest := io.tag
  ctrl.toRobValid := true.B
  ctrl.rfWen.foreach(_ := true.B);ctrl.fpWen.foreach(_ := true.B);ctrl.vecWen.foreach(_ := true.B)
  ctrl.fpu.foreach { f => f.fmt := io.format; f.rm := io.rm }
  ctrl.vpu.foreach { v =>
    v.vsew := io.format;v.vlmul := 0.U;v.vm := io.vm;v.vma := io.ma;v.vta := io.ta
    v.vstart := io.vstart;v.vuopIdx := io.uop;v.lastUop := true.B;v.vmask := io.mask
    v.sew8 := io.format===0.U;v.sew16 := io.format===1.U;v.sew32 := io.format===2.U;v.sew64 := io.format===3.U
    v.maskVecGen := Fill(v.maskVecGen.getWidth,1.U(1.W))
  }
  val data=Wire(new FuncUnitDataInput(cfg));data:=0.U.asTypeOf(data)
  data.src.zip(Seq(io.a,io.b,io.c,io.mask)).foreach {case (sink,value)=>sink:=value}
  data.vl.foreach(_:=io.vl)
  val redirect=Wire(Valid(new Redirect));redirect:=0.U.asTypeOf(redirect)
  redirect.valid:=io.flush;redirect.bits.robIdx.value:=io.tag-1.U
  val latency=cfg.latency.latencyVal.get
  val ctrls=ctrl +: Seq.fill(latency)(Reg(chiselTypeOf(ctrl)))
  val datas=data +: Seq.fill(latency)(Reg(chiselTypeOf(data)))
  val valids=io.valid +: Seq.fill(latency)(RegInit(false.B))
  for(i<-1 to latency){
    ctrls(i):=ctrls(i-1);datas(i):=datas(i-1)
    valids(i):=valids(i-1) && !ctrls(i-1).robIdx.needFlush(redirect)
  }
  for(dut<-Seq(hardware,behavior)){
    dut.io.in.bits:=0.U.asTypeOf(dut.io.in.bits)
    dut.io.in.valid:=io.valid;dut.io.out.ready:=io.ready;dut.io.flush:=redirect
    dut.io.in.bits.ctrl:=ctrl;dut.io.in.bits.data:=data
    dut.io.in.bits.ctrlPipe.get.zip(ctrls).foreach {case(a,b)=>a:=b}
    dut.io.in.bits.dataPipe.get.zip(datas).foreach {case(a,b)=>a:=b}
    dut.io.in.bits.validPipe.get.zip(valids).foreach {case(a,b)=>a:=b}
    dut.io.frm.foreach(_:=io.rm);dut.io.vxrm.foreach(_:=io.rm(1,0))
  }
  io.outValid:=hardware.io.out.valid
  io.equal:=(hardware.io.in.ready===behavior.io.in.ready) && (hardware.io.out.valid===behavior.io.out.valid) &&
    (!hardware.io.out.valid || hardware.io.out.bits.asUInt===behavior.io.out.bits.asUInt)
  io.result:=hardware.io.out.bits.res.data
  io.flags:=Cat(hardware.io.out.bits.res.vxsat.getOrElse(false.B),hardware.io.out.bits.res.fflags.getOrElse(0.U(5.W)))
}

object MultiplyWrapperStudyMain {
  def main(args:Array[String]):Unit={
    val out=Paths.get(args(0));Files.createDirectories(out)
    implicit val p:Parameters=(new top.TLConfig).alterPartial {
      case XSCoreParamsKey => XSCoreParameters()
      case utility.LogUtilsOptionsKey => utility.LogUtilsOptions(false,false,false)
    }
    val sv=ChiselStage.emitSystemVerilog(new MultiplyWrapperFixture(args(2)),
      args=Array("--firtool-binary-path",args(1)),
      firtoolOpts=Array("-O=release","--disable-all-randomization","--default-layer-specialization=enable",
        "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
    Files.writeString(out.resolve("MultiplyWrapperFixture.sv"),sv)
  }
}

package yunsuan.fpu {
  import chisel3._
  import chisel3.util._
  class ScalarProductReference extends Module {
    val io=IO(new Bundle {
      val a,b=Input(UInt(53.W));val format=Input(UInt(2.W));val fire=Input(Bool())
      val product=Output(UInt(107.W))
    })
    val booth=Module(new BoothEncoderF64F32F16(53,true))
    booth.io.in_a:=io.a;booth.io.in_b:=io.b
    booth.io.is_fp64:=io.format===3.U;booth.io.is_fp32:=io.format===2.U
    val tree=Module(new CSA_Nto2With3to2MainPipeline(booth.io.out_pp.length,107,5))
    tree.io.in:=booth.io.out_pp;tree.io.fire:=io.fire
    io.product:=tree.io.out_sum+tree.io.out_car
  }
}
package yunsuan.vector {
  import chisel3._
  import chisel3.util._
  class VectorProductReference extends Module {
    val io=IO(new Bundle {
      val a,b=Input(UInt(53.W));val format=Input(UInt(2.W));val fire=Input(Bool())
      val product=Output(UInt(107.W))
    })
    val booth=Module(new BoothEncoderF64F32F16(53,true))
    booth.io.in_a:=io.a;booth.io.in_b:=io.b
    booth.io.is_fp64:=io.format===3.U;booth.io.is_fp32:=io.format===2.U
    val tree=Module(new CSA_Nto2With3to2MainPipeline(booth.io.out_pp.length,107,5))
    tree.io.in:=booth.io.out_pp;tree.io.fire:=io.fire
    io.product:=tree.io.out_sum+tree.io.out_car
  }
}
package study.multiply {
  import chisel3._
  import chisel3.util._
  import _root_.circt.stage.ChiselStage
  import yunsuan.util.MultiplyBehavior
  import java.nio.file.{Files,Paths}
  class FloatProductFixture extends Module {
    val io=IO(new Bundle {
      val a,b=Input(UInt(53.W));val format=Input(UInt(2.W));val fire=Input(Bool())
      val equal=Output(Bool())
    })
    def packed(x:UInt):UInt=Mux(io.format===3.U,x,
      Mux(io.format===2.U,Cat(x(52,29),0.U(5.W),x(23,0)),
        Cat(x(52,42),0.U(2.W),x(39,29),0.U(5.W),x(23,13),0.U(2.W),x(10,0))))
    def scalar(x:UInt):UInt=Mux(io.format===3.U,x,Mux(io.format===2.U,x(23,0).pad(53),x(10,0).pad(53)))
    val s=Module(new yunsuan.fpu.ScalarProductReference)
    val v=Module(new yunsuan.vector.VectorProductReference)
    s.io.a:=scalar(io.a);s.io.b:=scalar(io.b);s.io.fire:=io.fire;s.io.format:=io.format
    v.io.a:=packed(io.a);v.io.b:=packed(io.b);v.io.fire:=io.fire;v.io.format:=io.format
    val sb=MultiplyBehavior.pipeline(MultiplyBehavior.significands(s.io.a,s.io.b,io.format===3.U,io.format===2.U,false),io.fire,1)
    val vb=MultiplyBehavior.pipeline(MultiplyBehavior.significands(v.io.a,v.io.b,io.format===3.U,io.format===2.U,true),io.fire,1)
    val format=RegEnable(io.format,io.fire)
    val mask=Mux(format===3.U,((BigInt(1)<<106)-1).U(107.W),Mux(format===2.U,
      ((((BigInt(1)<<48)-1)<<58)|((BigInt(1)<<48)-1)).U(107.W),
      Seq(0,26,58,84).map(offset=>((BigInt(1)<<22)-1)<<offset).reduce(_|_).U(107.W)))
    val scalarMask=Mux(format===3.U,((BigInt(1)<<106)-1).U(107.W),Mux(format===2.U,
      ((BigInt(1)<<48)-1).U(107.W),((BigInt(1)<<22)-1).U(107.W)))
    io.equal:=((s.io.product & scalarMask)===sb) && ((v.io.product & mask)===vb)
  }
  object FloatProductStudyMain {
    def main(args:Array[String]):Unit={
      val out=Paths.get(args(0));Files.createDirectories(out)
      val sv=ChiselStage.emitSystemVerilog(new FloatProductFixture,
        args=Array("--firtool-binary-path",args(1)),
        firtoolOpts=Array("-O=release","--disable-all-randomization","--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      Files.writeString(out.resolve("FloatProductFixture.sv"),sv)
    }
  }
}

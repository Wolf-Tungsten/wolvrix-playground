package study.groups

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import utility.SimulationModels
import java.nio.file.{Files, Paths}

class BehaviorGroupFixture(hardware: Boolean, rat: Boolean) extends Module {
  val lanes = if (rat) 520 else 3
  val rows = if (rat) Seq(32,32,32,1) else Seq(32,32)
  val widths = if (rat) Seq(8,8,8,8) else Seq(64,9)
  val io = IO(new Bundle {
    val valid = Input(Vec(lanes, Bool()))
    val kind = Input(Vec(lanes, UInt(4.W)))
    val index = Input(Vec(lanes, UInt(6.W)))
    val data = Input(Vec(lanes, UInt(64.W)))
    val readIndex = Input(UInt(5.W))
    val snapshot = Output(MixedVec(rows.zip(widths).map { case (n,w) => Vec(n, UInt(w.W)) }))
    val selected = Output(UInt(64.W))
    val vectorMapping = Output(Vec(if(rat) 64 else 1, UInt(9.W)))
  })
  def initial(bank: Int, row: Int): UInt =
    (if(bank==0) 0 else row).U(widths(bank).W)
  def enabled(bank: Int, lane: Int): Bool = {
    val base = io.valid(lane) && io.kind(lane)(bank)
    if(!rat || bank==0 || bank==3) base
    else base && io.index(lane)<32.U && (if(bank==2) io.index(lane)=/=0.U else true.B)
  }
  def address(bank: Int,lane: Int): UInt = if(rows(bank)==1) 0.U(1.W) else io.index(lane)(4,0)
  if (hardware) {
    val states=rows.indices.map(b => RegInit(VecInit((0 until rows(b)).map(i => initial(b,i)))))
    for(lane<-0 until lanes; bank<-rows.indices) {
      when(enabled(bank,lane)) { states(bank)(address(bank,lane)) := (if(!rat && bank==1 && lane==2) io.data(lane)(8,0) ^ states(0)(0)(8,0) else io.data(lane)(widths(bank)-1,0)) }
    }
    io.snapshot.zip(states).foreach { case (out,state) => out:=state }
    io.selected:=states.head(io.readIndex)
  } else {
    SimulationModels.model("commit-rat",clock,reset,observerOnly=true,commitBoundary="rising clock",updateGroup="ordered-arrays") { ctx =>
      ctx.capability("rat");ctx.input("updates",io.valid.asUInt)
      val states=rows.indices.map(b => ctx.array(s"state$b",rows(b),(i:Int)=>initial(b,i)))
      for(lane<-0 until lanes; bank<-rows.indices)
        states(bank).update(enabled(bank,lane),address(bank,lane),
          if(!rat && bank==1 && lane==2) io.data(lane)(8,0) ^ states(0).read(0.U)(8,0) else io.data(lane)(widths(bank)-1,0))
      io.snapshot.zip(states).foreach {case(out,state)=>out:=state.snapshot}
      io.selected:=states.head.read(io.readIndex)
      ctx.output("snapshots",io.snapshot.asUInt);ctx.check("snapshots",io.snapshot.asUInt)
    }
  }
  if(rat) {
    for(row<-0 until 32) {
      val physical=if(row==0) io.snapshot(3)(0).pad(9) else io.snapshot(2)(row).pad(9)+22.U
      io.vectorMapping(2*row):=physical<<1
      io.vectorMapping(2*row+1):=(physical<<1)+1.U
    }
  } else {io.vectorMapping(0):=0.U}
}
object BehaviorStateGroupStudyMain {
  def main(args:Array[String]):Unit={
    require(args.length==4,"<output> <firtool> <simple|rat> <hardware|model>")
    val out=Paths.get(args(0));Files.createDirectories(out)
    val hardware=args(3)=="hardware"
    SimulationModels.withMode(if(hardware)"hardware" else "commit-rat",Some(out.resolve("simulation_models.json")),
      lowering=if(hardware)"ordinary" else "grouped") {
      val sv=ChiselStage.emitSystemVerilog(new BehaviorGroupFixture(hardware,args(2)=="rat"),
        args=Array("--firtool-binary-path",args(1)),
        firtoolOpts=Array("-O=release","--disable-all-randomization","--default-layer-specialization=enable",
          "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
      Files.writeString(out.resolve("BehaviorGroupFixture.sv"),sv)
    }
  }
}

package study.intrinsics

import chisel3._
import chisel3.util.BitPat
import _root_.circt.stage.ChiselStage
import utility.{ListLookup, SimulationPrimitives}
import java.nio.file.{Files, Paths}

class DecodeTableAPIStudy extends RawModule {
  val in = IO(Input(UInt(3.W)))
  val dynamic = IO(Input(UInt(9.W)))
  val flag = IO(Output(Bool()))
  val out = IO(Output(UInt(9.W)))
  val unknownOut = IO(Output(UInt(4.W)))
  val conditional = IO(Output(Bool()))
  val selected: Bool = ListLookup(in,List(false.B),Array(BitPat("b1??") -> List(true.B))).head
  flag := selected
  out := ListLookup(in,List(dynamic),Array(BitPat("b001") -> List(3.U(9.W)))).head
  val unknown = Wire(UInt())
  unknown := in
  unknownOut := ListLookup(unknown,List(0.U(4.W)),Array(BitPat("b010") -> List(7.U(4.W)))).head
  conditional := false.B
  when(in(0)) {
    conditional := ListLookup(in,List(false.B),Array(BitPat("b101") -> List(true.B))).head
  }
}

object DecodeTableAPIStudyMain {
  def main(args: Array[String]): Unit = {
    val root=Paths.get(args(0));Files.createDirectories(root)
    def emit(name:String): Unit = Files.writeString(root.resolve(name+".sv"),
      ChiselStage.emitSystemVerilog(new DecodeTableAPIStudy,
        args=Array("--firtool-binary-path",args(1)),firtoolOpts=Array("--disable-all-randomization", "--default-layer-specialization=enable")))
    SimulationPrimitives.withMode("decode-table",Some(root.resolve("B.json"))) { emit("B") }
    SimulationPrimitives.withMode("none",Some(root.resolve("A.json"))) { emit("A") }
    emit("after-scope")
  }
}

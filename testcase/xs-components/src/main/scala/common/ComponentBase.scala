package xscomponents

import chisel3._

class XsComponentIO extends Bundle {
  val in0 = Input(UInt(64.W))
  val in1 = Input(UInt(64.W))
  val in2 = Input(UInt(64.W))
  val in3 = Input(UInt(64.W))
  val in4 = Input(UInt(64.W))
  val in5 = Input(UInt(64.W))
  val ctrl = Input(UInt(64.W))
  val out0 = Output(UInt(64.W))
  val out1 = Output(UInt(64.W))
  val out2 = Output(UInt(64.W))
  val out3 = Output(UInt(64.W))
  val flags = Output(UInt(64.W))
  val checksum = Output(UInt(64.W))
}

abstract class XsComponentModule extends Module {
  val io = IO(new XsComponentIO)
}


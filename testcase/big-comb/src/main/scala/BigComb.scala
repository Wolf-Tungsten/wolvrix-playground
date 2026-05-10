package bigcomb

import chisel3._
import chisel3.util._

class BigComb extends Module {
  val io = IO(new Bundle {
    val in0 = Input(UInt(64.W))
    val in1 = Input(UInt(64.W))
    val in2 = Input(UInt(64.W))
    val in3 = Input(UInt(64.W))
    val in4 = Input(UInt(64.W))
    val in5 = Input(UInt(64.W))
    val in6 = Input(UInt(64.W))
    val in7 = Input(UInt(64.W))
    val in8 = Input(UInt(64.W))
    val in9 = Input(UInt(64.W))
    val in10 = Input(UInt(64.W))
    val in11 = Input(UInt(64.W))
    val in12 = Input(UInt(64.W))
    val in13 = Input(UInt(64.W))
    val in14 = Input(UInt(64.W))
    val in15 = Input(UInt(64.W))
    val in16 = Input(UInt(64.W))
    val in17 = Input(UInt(64.W))
    val in18 = Input(UInt(64.W))
    val in19 = Input(UInt(64.W))
    val in20 = Input(UInt(64.W))
    val in21 = Input(UInt(64.W))
    val in22 = Input(UInt(64.W))
    val in23 = Input(UInt(64.W))
    val in24 = Input(UInt(64.W))
    val in25 = Input(UInt(64.W))
    val in26 = Input(UInt(64.W))
    val in27 = Input(UInt(64.W))
    val in28 = Input(UInt(64.W))
    val in29 = Input(UInt(64.W))
    val in30 = Input(UInt(64.W))
    val in31 = Input(UInt(64.W))
    val ctrl = Input(UInt(64.W))
    val sel = Input(UInt(16.W))
    val out0 = Output(UInt(64.W))
    val out1 = Output(UInt(64.W))
    val out2 = Output(UInt(64.W))
    val out3 = Output(UInt(64.W))
    val out4 = Output(UInt(64.W))
    val out5 = Output(UInt(64.W))
    val out6 = Output(UInt(64.W))
    val out7 = Output(UInt(64.W))
    val out8 = Output(UInt(64.W))
    val out9 = Output(UInt(64.W))
    val out10 = Output(UInt(64.W))
    val out11 = Output(UInt(64.W))
    val out12 = Output(UInt(64.W))
    val out13 = Output(UInt(64.W))
    val out14 = Output(UInt(64.W))
    val out15 = Output(UInt(64.W))
    val flags = Output(UInt(64.W))
    val checksum = Output(UInt(64.W))
  })

  private def rotl64(x: UInt, n: Int): UInt = Cat(x(63 - n, 0), x(63, 64 - n))
  private def rotr64(x: UInt, n: Int): UInt = Cat(x(n - 1, 0), x(63, n))
  private def low64(x: UInt): UInt = x(63, 0)
  private def add64(a: UInt, b: UInt): UInt = (a +& b)(63, 0)
  private def sub64(a: UInt, b: UInt): UInt = (a -& b)(63, 0)

  val seed = VecInit(Seq(
    io.in0, io.in1, io.in2, io.in3, io.in4, io.in5, io.in6, io.in7,
    io.in8, io.in9, io.in10, io.in11, io.in12, io.in13, io.in14, io.in15,
    io.in16, io.in17, io.in18, io.in19, io.in20, io.in21, io.in22, io.in23,
    io.in24, io.in25, io.in26, io.in27, io.in28, io.in29, io.in30, io.in31,
  ))

  val byteOps = VecInit((0 until 64).map { i =>
    val a = seed(i % 32)((i % 8) * 8 + 7, (i % 8) * 8)
    val b = seed((i * 7 + 3) % 32)(((i + 3) % 8) * 8 + 7, ((i + 3) % 8) * 8)
    val c = (a +& b)(7, 0) ^ Reverse(a) ^ Fill(8, io.sel(i % 16))
    val d = Mux(io.ctrl((i + 11) % 64), c, (a - b)(7, 0))
    d
  })

  val halfOps = VecInit((0 until 64).map { i =>
    val a = seed((i * 5 + 1) % 32)(((i + 1) % 4) * 16 + 15, ((i + 1) % 4) * 16)
    val b = seed((i * 9 + 2) % 32)(((i + 2) % 4) * 16 + 15, ((i + 2) % 4) * 16)
    val sum = (a +& b)(15, 0)
    val prod = ((a(7, 0) << 3) ^ (b(7, 0) << 1) ^ (a(7, 0) +& b(7, 0))).pad(16)(15, 0)
    MuxLookup(io.sel(1, 0), sum)(Seq(
      0.U -> (sum ^ prod),
      1.U -> ((a & b) | (~a & 0xffff.U)),
      2.U -> (Cat(a(7, 0), b(15, 8)) + prod),
      3.U -> Mux(a.asSInt < b.asSInt, a, b),
    ))
  })

  val lanes = Wire(Vec(64, UInt(64.W)))
  for (i <- 0 until 64) {
    val a = seed(i % 32)
    val b = seed((i * 7 + 5) % 32)
    val c = seed((i * 11 + 13) % 32)
    val sh = io.ctrl((i % 10) + 5, i % 10)
    val rotA = if ((i & 1) == 0) rotl64(a, (i % 31) + 1) else rotr64(a, (i % 31) + 1)
    val addSub = Mux(io.sel(i % 16), add64(add64(a, b), i.U(64.W)), sub64(sub64(a, b), i.U(64.W)))
    val dynShift = Mux(io.ctrl((i + 17) % 64), low64(b << sh), b >> sh)
    val cmp = Cat(0.U(63.W), (a < b) ^ (a.asSInt < c.asSInt))
    val packedBytes = Cat(byteOps((i * 8 + 7) % 64), byteOps((i * 8 + 6) % 64),
      byteOps((i * 8 + 5) % 64), byteOps((i * 8 + 4) % 64),
      byteOps((i * 8 + 3) % 64), byteOps((i * 8 + 2) % 64),
      byteOps((i * 8 + 1) % 64), byteOps((i * 8) % 64))
    lanes(i) := low64(MuxLookup(io.ctrl(i % 6 + 2, i % 6), addSub)(Seq(
      0.U -> low64(addSub ^ rotA),
      1.U -> low64((a & b) | (~c)),
      2.U -> low64(dynShift ^ packedBytes),
      3.U -> low64(Cat(halfOps((i * 2 + 1) % 64), halfOps((i * 2) % 64), halfOps((i * 2 + 9) % 64), halfOps((i * 2 + 8) % 64))),
      4.U -> low64(cmp ^ PopCount(a).pad(64) ^ PriorityEncoder(b).pad(64)),
      5.U -> low64(add64(a ^ (b << 7)(63, 0), (b ^ (a >> 5))) ^ c),
      6.U -> low64(Reverse(a) ^ Fill(64, io.ctrl((i + 29) % 64))),
      7.U -> low64(Mux1H(Seq(io.sel(0) -> a, io.sel(1) -> b, io.sel(2) -> c, io.sel(3) -> rotA))),
    )))
  }

  val rounds = Seq.tabulate(8) { r =>
    VecInit((0 until 64).map { i =>
      val a = lanes((i + r * 3) % 64)
      val b = lanes((i * 5 + r * 7 + 1) % 64)
      val c = lanes((i * 11 + r * 13 + 2) % 64)
      val h0 = halfOps((i + r * 5) % 64).pad(64)
      val pc = PopCount(a ^ b).pad(64)
      val wide = Cat(a(15, 0), b(31, 16), c(47, 32), halfOps((i + r) % 64))
      val branchy = Mux(io.ctrl((i + r) % 64), add64(add64(a, b), pc), a ^ b ^ c)
      low64(MuxLookup(io.sel((i + r) % 16, (i + r) % 16), branchy)(Seq(
        0.U -> low64(branchy ^ wide),
        1.U -> low64(add64(rotl64(a, ((i + r) % 31) + 1), h0)),
        2.U -> low64(rotr64(b, ((i + 2 * r) % 31) + 1) ^ c),
        3.U -> low64(Mux(a.asSInt > b.asSInt, sub64(a, c), add64(b, c))),
      )))
    })
  }

  val finalLanes = VecInit((0 until 64).map { i =>
    rounds.map(_(i)).reduce(_ ^ _) ^ lanes(i)
  })
  val group = VecInit((0 until 16).map { i =>
    val a = finalLanes(i * 4)
    val b = finalLanes(i * 4 + 1)
    val c = finalLanes(i * 4 + 2)
    val d = finalLanes(i * 4 + 3)
    val mixed = add64(a, b) ^ rotl64(c, (i % 23) + 1) ^ rotr64(d, (i % 19) + 1)
    mixed ^ PopCount(Cat(a(15, 0), b(15, 0), c(15, 0), d(15, 0))).pad(64)
  })

  io.out0 := group(0)
  io.out1 := group(1)
  io.out2 := group(2)
  io.out3 := group(3)
  io.out4 := group(4)
  io.out5 := group(5)
  io.out6 := group(6)
  io.out7 := group(7)
  io.out8 := group(8)
  io.out9 := group(9)
  io.out10 := group(10)
  io.out11 := group(11)
  io.out12 := group(12)
  io.out13 := group(13)
  io.out14 := group(14)
  io.out15 := group(15)
  io.flags := Cat((0 until 64).reverse.map { i =>
    val a = finalLanes(i)
    val b = finalLanes((i * 7 + 3) % 64)
    (a === b) | (a < b) | (PopCount(a(31, 0)) > PopCount(b(31, 0)))
  })
  io.checksum := group.reduce(_ ^ _) ^ io.flags ^ io.ctrl ^ io.sel.pad(64)
}

object BigCombMain extends App {
  import chisel3.stage.ChiselGeneratorAnnotation
  import _root_.circt.stage.ChiselStage

  (new ChiselStage).execute(args, Seq(
    ChiselGeneratorAnnotation(() => new BigComb)
  ))
}

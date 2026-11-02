// Research wrappers around the pinned Chisel / XiangShan utility implementations.
// These are isolated parameter instances, not extracted whole XiangShan modules.
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

class PatternStudy(kind: String) extends Module {
  override def desiredName = "Pattern"
  val io = IO(new Bundle {
    val a = Input(UInt(64.W))
    val b = Input(UInt(64.W))
    val c = Input(UInt(64.W))
    val d = Input(UInt(64.W))
    val sel = Input(UInt(8.W))
    val y = Output(UInt(64.W))
    val z = Output(UInt(64.W))
  })
  io.y := 0.U
  io.z := 0.U
  val bytes = VecInit((0 until 8).map(i => io.a(8*i+7, 8*i)))
  kind match {
    case "popcount16" => io.y := PopCount(io.a(15,0))
    case "popcount64" => io.y := PopCount(io.a)
    case "popcount32" => io.y := PopCount(io.a(31,0))
    case "popcount_threshold" => io.y := PopCount.atLeast(2, io.a)
    case "ones_recursive" => io.y := utility.OnesMoreThan(io.a(11,0).asBools, 3)
    case "ones_recursive16" => io.y := utility.OnesMoreThan(io.a(15,0).asBools, 3)
    case "priority64" => io.y := Mux(io.a.orR, PriorityEncoder(io.a), 64.U)
    case "priority16" => io.y := Mux(io.a(15,0).orR, PriorityEncoder(io.a(15,0)), 16.U)
    case "oh_to_uint16" => io.y := OHToUInt(io.a(15,0))
    case "mux1h8" => io.y := Mux1H(io.b(7,0), bytes)
    case "mux1h4" => io.y := Mux1H(io.b(3,0), (0 until 4).map(i=>io.a(16*i+15,16*i)))
    case "priority_mux8" => io.y := utility.ParallelPriorityMux(io.b(7,0), bytes.toSeq)
    case "select4" =>
      val out = utility.SelectFirstN(io.a(15,0), 4, io.b(3,0))
      io.y := out.asUInt
    case "rotate8" =>
      val r = Wire(new utils.VecRotate(8, false, utils.VecRotate.Direction.Right))
      r.n := io.sel(2,0)
      io.y := r.rotate(bytes).asUInt
    case "barrel8" =>
      io.y := freechips.rocketchip.util.BarrelShifter.rightShift(bytes, io.sel(2,0)).asUInt
    case "reverse64" => io.y := Reverse(io.a)
    case "prefix_dense" | "prefix_ripple" =>
      val in = (0 until 16).map(i => Cat(0.U(4.W), io.a(i)))
      val p = if (kind == "prefix_dense") freechips.rocketchip.util.DensePrefixSum
              else freechips.rocketchip.util.RipplePrefixSum
      val packed = VecInit(p(in)((a: UInt, b: UInt) => a + b)).asUInt
      io.y := packed(63,0)
      io.z := packed(79,64)
    case "xor_fold" => io.y := utility.XORFold(io.a, 8)
    case "parity64" => io.y := io.a.xorR
    case "ecc32" => io.y := new utility.SECCode().encode(io.a(31,0))
    case "crc16" | "crc16_table" => io.y := freechips.rocketchip.util.CRC(BigInt(0x11021), io.a(31,0), 32)
    case "gray_decode32" => io.y := GrayToBinary(io.a(31,0))
    case "decode_table" =>
      // A complete 8-bit truth table, expressed through the actual Chisel lookup utility.
      io.y := MuxLookup(io.a(7,0), 0.U(8.W))((0 until 256).map(i =>
        i.U(8.W) -> (((i * 29) ^ (i >> 2) ^ 0xa7) & 255).U(8.W)))
    case "decode16" =>
      io.y := MuxLookup(io.a(3,0), 0.U(8.W))((0 until 16).map(i =>
        i.U(4.W) -> (((i * 29) ^ (i >> 2) ^ 0xa7) & 255).U(8.W)))
    case "cam8" =>
      // Same all-match contract as IndexableCAMTemplate, combinational read cone only.
      io.y := VecInit(bytes.map(_ === io.b(7,0))).asUInt
    case "sort4" | "sort4_network" =>
      // Exact three-layer compare/exchange sorting network; all lanes valid, unsigned keys.
      // This isolates network lowering, not HwSort's circular-pointer / invalid-lane contract.
      def swap(a: UInt, b: UInt) = (Mux(a <= b,a,b), Mux(a <= b,b,a))
      val x = (0 until 4).map(i => io.a(16*i+15,16*i))
      val (a,b) = swap(x(0),x(1)); val (c,d) = swap(x(2),x(3))
      val (e,f) = swap(a,c); val (g,h) = swap(b,d); val (i,j) = swap(f,g)
      io.y := Cat(h,j,i,e)
    case "csa64" =>
      val sum = io.a ^ io.b ^ io.c
      val carry = ((io.a & io.b) | (io.a & io.c) | (io.b & io.c)) << 1
      io.y := sum + carry
    case "wire64" => io.y := io.a
    case "native_add64" => io.y := io.a + io.b + io.c
    case "table16" | "table64" | "table64_indexed" =>
      val depth = if(kind=="table16")16 else 64
      val w = log2Ceil(depth)
      val table = RegInit(VecInit(Seq.fill(depth)(0.U(32.W))))
      when (io.sel(7)) { table(io.sel(w-1,0)) := io.a(31,0) }
      io.y := table(io.b(w-1,0))
      if(kind!="table64_indexed") io.z := table.reduce(_ ^ _)
    case "masked_write64" =>
      val state = RegInit(0.U(64.W))
      val next = WireInit(state)
      val lanes = Wire(Vec(8, UInt(8.W)))
      for (i <- 0 until 8) {
        lanes(i) := Mux(io.sel(i), io.a(8*i+7,8*i), state(8*i+7,8*i))
      }
      next := lanes.asUInt
      state := next
      io.y := state
    case "lfsr64" => io.y := utility.LFSR64(io.sel(0), Some(0x1234567887654321L))
    case "queue8" | "queue8_flow" =>
      val q = Module(new Queue(UInt(32.W), 8, pipe=false, flow=kind=="queue8_flow"))
      q.io.enq.valid := io.sel(0)
      q.io.enq.bits := io.a(31,0)
      q.io.deq.ready := io.sel(1)
      io.y := Mux(q.io.deq.valid, q.io.deq.bits, 0.U)
      io.z := Cat(q.io.count, q.io.enq.ready, q.io.deq.valid)
    case "cam8_state" =>
      val cam = Module(new utility.IndexableCAMTemplate(UInt(8.W),8,1,true)(org.chipsalliance.cde.config.Parameters.empty))
      val valid = RegInit(VecInit(Seq.fill(8)(false.B)))
      cam.io.w.valid := io.sel(7)
      cam.io.w.bits.index := io.sel(2,0)
      cam.io.w.bits.data := io.a(7,0)
      cam.io.r.req(0) := io.b(7,0)
      cam.io.ridx.get := io.c(2,0)
      when(io.sel(7)) {valid(io.sel(2,0)):=true.B}
      io.y := cam.io.r.resp(0).asUInt & valid.asUInt
      io.z := Mux(valid(io.c(2,0)),cam.io.rdata.get,0.U)
    case "gated_reg64" => io.y := utility.GatedRegNext(io.a,Some(0.U(64.W)))
    case "plain_reg64" => io.y := RegNext(io.a,0.U(64.W))
    case "bit_extract64" =>
      val f = Seq(0,3,7,11,16,21,25,28,33,38,42,47,50,55,59,63)
      val u = Module(new utility.UIntCompressor(64,f))
      u.io.in := io.a;io.y := u.io.out
    case "bit_deposit16" =>
      val f = Seq(0,3,7,11,16,21,25,28,33,38,42,47,50,55,59,63)
      val u = Module(new utility.UIntExtractor(64,f))
      u.io.in := io.a(15,0);io.y := u.io.out
    case "histogram8" =>
      // Bin update cone from XSPerfHistogram: [8,40), step 4, clipping both ends.
      // Logging and sum/mean counters are outside this isolated experiment.
      val bins = RegInit(VecInit(Seq.fill(8)(0.U(64.W))))
      for(i <- 0 until 8) {
        val inRange = io.a >= (8+i*4).U && io.a < (12+i*4).U
        val left = if(i==0) io.a < 8.U else false.B
        val right = if(i==7) io.a >= 40.U else false.B
        when(io.sel(0) && (inRange || left || right)) {bins(i):=bins(i)+1.U}
      }
      io.y := bins(io.b(2,0))
      io.z := bins.reduce(_ + _)
    case "guarded_div32" =>
      io.y := Mux(io.sel(0), io.a(31,0) / (io.b(31,0) | 1.U), 0.U)
    case "age8" =>
      // Explicit 8x8 matrix with a single enqueuing index; reset and all rows observable.
      val age = RegInit(VecInit(Seq.fill(8)(0.U(8.W))))
      for (i <- 0 until 8) {
        when (io.sel(7)) {
          age(i) := Mux(io.sel(2,0) === i.U, (1 << i).U,
            age(i) | UIntToOH(io.sel(2,0),8))
        }
      }
      val eligible = io.b(7,0)
      io.y := VecInit((0 until 8).map(i =>
        eligible(i) && ((age(i) | ~eligible).andR))).asUInt
      io.z := age.asUInt
    case _ => throw new IllegalArgumentException(kind)
  }
}

object PatternStudyMain {
  def main(args: Array[String]): Unit = {
    val destination = Paths.get(args(1))
    Files.createDirectories(destination)
    val sv = ChiselStage.emitSystemVerilog(new PatternStudy(args(0)),
      firtoolOpts=Array("-O=release", "--disable-all-randomization", "--default-layer-specialization=enable",
        "--lowering-options=disallowLocalVariables,disallowPackedArrays,disallowPortDeclSharing"))
    Files.writeString(destination.resolve("Pattern.sv"), sv)
  }
}

package xscomponents

import chisel3._
import chisel3.util._

// Faithful, self-contained extraction of the `metaQueueResolve` register from
//   testcase/xiangshan/src/main/scala/xiangshan/frontend/ftq/Ftq.scala:103
//     private val metaQueueResolve = Reg(Vec(FtqSize, new BpuResolveMeta))
// and its indexed write (Ftq.scala:186) / indexed read (Ftq.scala:336).
//
// The xs-components build is bare Chisel and cannot import the real XiangShan
// `Ftq` / `BpuResolveMeta` (they pull in cde.config.Parameters, utility.*,
// xiangshan.*, sub-modules, …). So the bundle hierarchy below is reconstructed
// with the SAME field names and widths as the real source, taken from
// build/xs/rtl/rtl/SimTop.fir (the `reg metaQueueResolve : {...}[64]` type):
//
//   mbtb.entries : Vec(NumAlignBanks=2, Vec(NumWay=4, MainBtbMetaEntry))   -> FIR [4][2]
//   tage.entries : Vec(NumBtbResultEntries=8, TageMetaEntry)               -> FIR [8]
//   sc.scPathResp: Vec(2, Vec(8, UInt(6)))  (Vec-of-UInt, FIR UInt<6>[8][2])
//
// Because the register is named `metaQueueResolve` and the sub-bundle val names
// match, firtool emits the identical scalarization
//   metaQueueResolve_<slot>_tage_entries_<e>_providerUsefulCtr_value, …
// and the identical 64-slot read gather  wire [63:0][W:0] _GEN_k = {…}; _GEN_k[idx].

class SaturateCounter(w: Int) extends Bundle { val value = UInt(w.W) }

class BranchAttribute extends Bundle {
  val branchType = UInt(2.W)
  val rasAction  = UInt(2.W)
}

class MainBtbMetaEntry extends Bundle {
  val rawHit    = Bool()
  val position  = UInt(5.W)
  val attribute = new BranchAttribute
  val counter   = new SaturateCounter(2)
}

class MainBtbMeta extends Bundle {
  val entries = Vec(2, Vec(4, new MainBtbMetaEntry)) // Vec(NumAlignBanks, Vec(NumWay, …)) -> FIR [4][2]
}

class TageMetaEntry extends Bundle {
  val useProvider       = Bool()
  val providerTableIdx  = UInt(3.W)
  val providerWayIdx    = UInt(2.W)
  val providerTakenCtr  = new SaturateCounter(3)
  val providerUsefulCtr = new SaturateCounter(2)
  val altOrBasePred     = Bool()
}

class TageMeta extends Bundle {
  val entries = Vec(8, new TageMetaEntry)
}

class ScMeta extends Bundle {
  val scPathResp = Vec(2, Vec(8, UInt(6.W)))
}

class BpuResolveMeta extends Bundle {
  val mbtb = new MainBtbMeta
  val tage = new TageMeta
  val sc   = new ScMeta
}

class XsRealFtqMetaQueueResolve extends Module {
  val io = IO(new Bundle {
    val in0  = Input(UInt(64.W))
    val in1  = Input(UInt(64.W))
    val in2  = Input(UInt(64.W))
    val in3  = Input(UInt(64.W))
    val in4  = Input(UInt(64.W))
    val in5  = Input(UInt(64.W))
    val ctrl = Input(UInt(64.W))
    val out0     = Output(UInt(64.W))
    val out1     = Output(UInt(64.W))
    val out2     = Output(UInt(64.W))
    val out3     = Output(UInt(64.W))
    val flags    = Output(UInt(64.W))
    val checksum = Output(UInt(64.W))
  })

  private val FtqSize = 64

  // The register堆: 64 槽 × 一个 BpuResolveMeta（与 Ftq.scala:103 同形）。
  // 真实 Ftq 里是无 reset 的 `Reg(Vec(...))`；这里为了让 gsim/grhsim 从同一确定初值出发、
  // 可在 xs-component bench 中逐周期一致性校验，改用 RegInit(0)。这不改变 Vec-of-Bundle
  // 的标量化、per-slot 写口或 _GEN[idx] 读 gather 结构。
  val metaQueueResolve = RegInit(0.U.asTypeOf(Vec(FtqSize, new BpuResolveMeta)))

  private def rotl(x: UInt, n: Int): UInt = Cat(x(63 - n, 0), x(63, 64 - n))
  private def mix(a: UInt, b: UInt, salt: Int): UInt = {
    val x = a ^ rotl(b, (salt % 31) + 1) ^ (BigInt("9e3779b97f4a7c15", 16) + salt).U(64.W)
    x + rotl(a ^ b, (salt % 23) + 1)
  }

  // ---- 写口（Ftq.scala:184-186）: when(meta.valid) metaQueueResolve(s3FtqPtr) := resolveMeta ----
  private val metaValid = io.ctrl(0)
  private val s3FtqPtr  = io.in0(5, 0)

  // 用输入混出 288-bit 写数据，再 asTypeOf 成整条 BpuResolveMeta（驱动所有字段）。
  private val w0 = mix(io.in1, io.in2, 1)
  private val w1 = mix(io.in3, io.in4, 2)
  private val w2 = mix(io.in5, io.ctrl, 3)
  private val w3 = mix(w0, w2, 4)
  private val w4 = mix(w1, io.in0, 5)
  private val wide = Cat(w0, w1, w2, w3, w4) // 320 bits
  private val resolveMeta = wide(287, 0).asTypeOf(new BpuResolveMeta)

  when(metaValid) {
    metaQueueResolve(s3FtqPtr) := resolveMeta
  }

  // ---- 读口（Ftq.scala:336）: train.meta := metaQueueResolve(trainFtqIdx) ----
  private val trainFtqIdx = io.in1(5, 0)
  private val trainMeta   = metaQueueResolve(trainFtqIdx)

  // 显式读出几个具名字段，确保 _GEN_k[idx] 这类 per-field select 真实存在、不被消除。
  private val pufc0 = trainMeta.tage.entries(0).providerUsefulCtr.value          // 2-bit，对应正文 _GEN_90
  private val tag0  = trainMeta.tage.entries(io.in2(2, 0)).providerTakenCtr.value // 动态 entry 下标
  private val mbtb0 = trainMeta.mbtb.entries(io.in3(0))(io.in3(2, 1)).position    // [bank][way].position
  private val scp0  = trainMeta.sc.scPathResp(io.in4(0))(io.in4(3, 1))            // Vec-of-UInt 动态读

  private val flat = trainMeta.asUInt // 288 bits 全字段读出

  io.out0     := Cat(0.U(62.W), pufc0)
  io.out1     := flat(63, 0) ^ flat(127, 64)
  io.out2     := flat(191, 128) ^ flat(255, 192)
  io.out3     := Cat(0.U(61.W), tag0) ^ Cat(0.U(59.W), mbtb0) ^ Cat(0.U(58.W), scp0)
  io.flags    := Cat(0.U(63.W), metaValid)
  io.checksum := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ flat(287, 256)
}

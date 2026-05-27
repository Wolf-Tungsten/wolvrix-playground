package xscomponents

import chisel3._
import chisel3.util._

// Additional reduced extracts from real XiangShan implementation paths. These
// modules keep the standalone xs-components IO ABI while preserving the dense
// selection, banking, priority, and state-update shapes that are relevant for
// GSIM vs GrhSIM performance comparison.

class XsPlruBankedXLarge extends XsComponentModule {
  import XsCommon._

  private val sets = 128
  private val ways = 8
  private val stateBits = ways - 1
  private val ports = 4

  val touchBase = io.in0(6, 0)
  val victimBase = io.in1(6, 0)
  val wayMask = io.in2(ways - 1, 0)
  val validMask = io.in3(ways - 1, 0)
  val touchWays = VecInit((0 until ports).map(i => (io.ctrl(3 * i + 2, 3 * i) ^ i.U)(2, 0)))
  val touchEn = io.in4(ports - 1, 0) | io.ctrl(ports + 15, 16)

  def victim(st: UInt): UInt = {
    val b0 = !st(0)
    val b1 = Mux(b0, !st(1), !st(4))
    val b2 = MuxLookup(Cat(b0, b1), !st(2))(Seq(
      0.U -> !st(2),
      1.U -> !st(3),
      2.U -> !st(5),
      3.U -> !st(6),
    ))
    Cat(b0, b1, b2)
  }

  def next(st: UInt, way: UInt): UInt = {
    var n = st
    n = Mux(way(2), n | 1.U, n & ~1.U(stateBits.W))
    n = Mux(!way(2) && way(1), n | 2.U, n & ~2.U(stateBits.W))
    n = Mux(way(2) && way(1), n | 16.U, n & ~16.U(stateBits.W))
    n = Mux(way(2, 1) === 0.U && way(0), n | 4.U, n & ~4.U(stateBits.W))
    n = Mux(way(2, 1) === 1.U && way(0), n | 8.U, n & ~8.U(stateBits.W))
    n = Mux(way(2, 1) === 2.U && way(0), n | 32.U, n & ~32.U(stateBits.W))
    n = Mux(way(2, 1) === 3.U && way(0), n | 64.U, n & ~64.U(stateBits.W))
    n
  }

  val baseState = VecInit((0 until sets).map { set =>
    (io.in4 >> ((set % 9) * 7))(stateBits - 1, 0) ^ ((set * 17).U(16.W))(stateBits - 1, 0)
  })
  val nextState = VecInit((0 until sets).map { set =>
    var cur = baseState(set)
    for (port <- 0 until ports) {
      val idx = touchBase + (set * 3 + port * 17).U
      cur = Mux(touchEn(port) && idx === set.U, next(cur, touchWays(port)), cur)
    }
    cur
  })

  val victimWays = VecInit((0 until ports).map { port =>
    val set = victimBase + (port * 29).U
    val raw = victim(baseState(set))
    val candidates = wayMask & validMask
    Mux(candidates(raw), raw, PriorityEncoder(candidates))
  })
  val sample = VecInit((0 until 16).map(i => Cat(0.U(57.W), nextState(i)))).reduce(_ ^ _)
  io.out0 := sample
  io.out1 := Cat(0.U(52.W), victimWays.asUInt)
  io.out2 := Cat(0.U(56.W), wayMask ^ validMask)
  io.out3 := mix64(io.out0, io.out1, 31)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from backend/rename/freelist/StdFreeList.scala pointer, PopCount,
// dynamic Vec read, and free/allocate update paths.
class XsFreeListAllocLarge extends XsComponentModule {
  import XsCommon._

  private val freeListSize = 128
  private val renameWidth = 6
  private val commitWidth = 6
  val freeList = VecInit((0 until freeListSize).map(i => (io.in3(7, 0) + (i + 32).U(8.W)) ^ io.in4(7, 0)))
  val head = io.in2(6, 0)
  val tail = io.in5(6, 0)
  val allocReq = io.ctrl(renameWidth - 1, 0)
  val freeReq = io.ctrl(15, 10)
  val walkReq = io.ctrl(25, 20)
  val redirect = io.ctrl(31)

  val allocOffsets = VecInit((0 until renameWidth).map(i => PopCount(allocReq(i, 0))))
  val freeOffsets = VecInit((0 until commitWidth).map(i => PopCount(freeReq(i, 0))))
  def countBefore(bits: UInt, i: Int): UInt = if (i == 0) 0.U else PopCount(bits(i - 1, 0))
  val allocRegs = VecInit((0 until renameWidth).map { i =>
    val idx = head + countBefore(allocReq, i)
    Mux(allocReq(i), freeList(idx), 0.U)
  })

  val allocCount = PopCount(allocReq)
  val freeCount = PopCount(freeReq)
  val walkCount = PopCount(walkReq)
  val nextHead = Mux(redirect, io.in2(6, 0), head + allocCount + walkCount)
  val nextTail = tail + freeCount

  io.out0 := Cat(0.U(16.W), allocRegs.asUInt)
  io.out1 := Cat(0.U(57.W), nextHead) ^ Cat(0.U(57.W), nextTail)
  io.out2 := Cat(0.U(58.W), allocOffsets.asUInt(5, 0)) ^ Cat(0.U(58.W), freeOffsets.asUInt(5, 0))
  io.out3 := mix64(io.out0, io.out1, 37)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from backend/rob/Rob.scala banked entry scan, enqueue hit vectors,
// writeback update, and commit-line read shape.
class XsRobBankScanLarge extends XsComponentModule {
  import XsCommon._

  private val entries = 128
  private val banks = 8
  private val commitWidth = 8
  val valid = VecInit((0 until entries).map(i => io.in3(i % 64) ^ io.ctrl(i % 32)))
  val flags = VecInit((0 until entries).map(i => ((io.in2 >> ((i % 16) * 4))(3, 0) ^ (i & 0xf).U(4.W))))
  val enqBase = io.in0(6, 0)
  val wbBase = io.in1(6, 0)
  val deqBase = io.in4(6, 0)
  val enqReq = io.ctrl(7, 0)
  val wbReq = io.ctrl(15, 8)
  val flush = io.ctrl(31)
  def countBefore(bits: UInt, i: Int): UInt = if (i == 0) 0.U else PopCount(bits(i - 1, 0))

  val enqHits = VecInit((0 until entries).map { i =>
    VecInit((0 until commitWidth).map(p => enqReq(p) && !flush && (enqBase + countBefore(enqReq, p)) === i.U)).asUInt.orR
  })
  val wbHits = VecInit((0 until entries).map { i =>
    VecInit((0 until commitWidth).map(p => wbReq(p) && (wbBase + (p * 13).U) === i.U)).asUInt.orR
  })
  val effValid = VecInit((0 until entries).map(i => valid(i) || enqHits(i)))
  val effFlags = VecInit((0 until entries).map(i => flags(i) | Cat(0.U(3.W), wbHits(i))))

  val lineIdx = VecInit((0 until banks).map(i => deqBase + i.U))
  val lineValid = VecInit(lineIdx.map(idx => effValid(idx))).asUInt
  val lineFlags = VecInit(lineIdx.map(idx => effFlags(idx))).asUInt
  val commitMask = VecInit((0 until banks).map(i => lineValid(i) && !lineFlags(4 * i))).asUInt
  val commitCount = PriorityEncoderOH((~commitMask)(banks - 1, 0) | (1.U << (banks - 1)).asUInt)
  val nextDeqBase = Mux(flush, io.in4(6, 0), deqBase + PopCount(commitMask))

  io.out0 := Cat(0.U(56.W), lineValid)
  io.out1 := Cat(0.U(32.W), lineFlags)
  io.out2 := Cat(0.U(56.W), commitMask)
  io.out3 := mix64(Cat(0.U(56.W), commitCount), Cat(0.U(57.W), nextDeqBase), 41)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from backend/issue/FuBusyTableRead.scala latency-bucket to entry
// mask expansion.
class XsIssueBusyMaskLarge extends XsComponentModule {
  import XsCommon._

  private val entries = 64
  private val latencies = 8
  val fuTypes = RegInit(VecInit(Seq.fill(entries)(0.U(8.W))))
  val seed = io.in0 ^ io.ctrl
  for (i <- 0 until entries) {
    fuTypes(i) := (seed((i % 8) + 7, i % 8) ^ (1 << (i % 8)).U)(7, 0)
  }
  val busy = io.in1(latencies - 1, 0)
  val readMasks = VecInit((0 until latencies).map { lat =>
    val typesForLatency = ((1 << lat) | (1 << ((lat + 3) % 8)) | (1 << ((lat + 5) % 8))).U(8.W)
    VecInit((0 until entries).map(i => busy(lat) && (fuTypes(i) & typesForLatency).orR)).asUInt
  })
  val combined = readMasks.reduce(_ | _)
  val wake = VecInit((0 until entries).map(i => combined(i) ^ io.in2(i % 64))).asUInt

  io.out0 := combined
  io.out1 := wake
  io.out2 := Cat(0.U(57.W), PopCount(combined))
  io.out3 := mix64(combined, wake, 43)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from backend/datapath/WbArbiter.scala writeback port grouping and
// priority selection.
class XsWbArbiterLarge extends XsComponentModule {
  import XsCommon._

  private val inputs = 16
  private val ports = 5
  val valid = VecInit((0 until inputs).map(i => io.in0(i) ^ io.ctrl(i)))
  val port = VecInit((0 until inputs).map(i => (io.in1(3 * i + 2, 3 * i) + i.U)(2, 0)))
  val priority = VecInit((0 until inputs).map(i => (io.in2(2 * i + 1, 2 * i) ^ (i % 4).U)(1, 0)))
  val data = VecInit((0 until inputs).map(i => io.in3 ^ (BigInt(i) * 0x9e37).U(64.W) ^ rotl(io.in4, (i % 17) + 1)))
  val outData = Wire(Vec(ports, UInt(64.W)))
  val outValid = Wire(Vec(ports, Bool()))

  for (p <- 0 until ports) {
    val candidates = VecInit((0 until inputs).map(i => valid(i) && port(i) === p.U)).asUInt
    val prio0 = VecInit((0 until inputs).map(i => candidates(i) && priority(i) === 0.U)).asUInt
    val prio1 = VecInit((0 until inputs).map(i => candidates(i) && priority(i) === 1.U)).asUInt
    val prio2 = VecInit((0 until inputs).map(i => candidates(i) && priority(i) === 2.U)).asUInt
    val selected = Mux(prio0.orR, PriorityEncoderOH(prio0),
                   Mux(prio1.orR, PriorityEncoderOH(prio1),
                   Mux(prio2.orR, PriorityEncoderOH(prio2), PriorityEncoderOH(candidates))))
    outValid(p) := candidates.orR
    outData(p) := Mux1H(selected, data)
  }

  io.out0 := outData.reduce(_ ^ _)
  io.out1 := Cat(0.U(59.W), outValid.asUInt)
  io.out2 := Cat(0.U(48.W), port.asUInt(15, 0))
  io.out3 := mix64(io.out0, io.out1, 47)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from backend/decode/FusionDecoder.scala two-instruction fusion
// predicate fanout.
class XsFusionDecodeLarge extends XsComponentModule {
  import XsCommon._

  private val pairs = 8
  val instA = VecInit((0 until pairs).map(i => (io.in0 >> (i * 3)) ^ rotl(io.in1, i + 1)))
  val instB = VecInit((0 until pairs).map(i => (io.in2 >> (i * 5)) ^ rotr(io.in3, i + 2)))
  val rdA = VecInit((0 until pairs).map(i => instA(i)(11, 7)))
  val rs1B = VecInit((0 until pairs).map(i => instB(i)(19, 15)))
  val rs2B = VecInit((0 until pairs).map(i => instB(i)(24, 20)))
  val sameDest = VecInit((0 until pairs).map(i => rdA(i) === instB(i)(11, 7)))
  val destToRs1 = VecInit((0 until pairs).map(i => rdA(i) === rs1B(i)))
  val destToRs2 = VecInit((0 until pairs).map(i => rdA(i) === rs2B(i)))

  def opcode(x: UInt): UInt = x(6, 0)
  def funct3(x: UInt): UInt = x(14, 12)
  def shamt(x: UInt): UInt = x(25, 20)
  val fused = VecInit((0 until pairs).map { i =>
    val slliSrli = opcode(instA(i)) === "b0010011".U && funct3(instA(i)) === 1.U &&
      opcode(instB(i)) === "b0010011".U && funct3(instB(i)) === 5.U &&
      (shamt(instA(i)) === 32.U || shamt(instA(i)) === 48.U) && sameDest(i) && destToRs1(i)
    val shiftAdd = opcode(instA(i)) === "b0010011".U && funct3(instA(i)) === 1.U &&
      opcode(instB(i)) === "b0110011".U && funct3(instB(i)) === 0.U &&
      shamt(instA(i)) <= 4.U && sameDest(i) && (destToRs1(i) || destToRs2(i))
    val logicExtract = (funct3(instA(i)) === 4.U || funct3(instA(i)) === 6.U || funct3(instA(i)) === 7.U) &&
      opcode(instB(i)) === "b0010011".U && funct3(instB(i)) === 7.U && instB(i)(31, 20) === 1.U &&
      sameDest(i) && destToRs1(i)
    slliSrli || shiftAdd || logicExtract
  })
  val rsMux = VecInit((0 until pairs).map(i => Mux(destToRs1(i), rs2B(i), rs1B(i)))).asUInt
  io.out0 := Cat(0.U(56.W), fused.asUInt)
  io.out1 := Cat(0.U(24.W), rsMux)
  io.out2 := Cat(0.U(56.W), sameDest.asUInt)
  io.out3 := mix64(io.out0, io.out1, 53)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from cache/mmu/TLBStorage.scala and TLB permission match paths.
class XsTlbPermLarge extends XsComponentModule {
  import XsCommon._

  private val entries = 32
  val tags = VecInit((0 until entries).map(i => (io.in3(43, 0) ^ (i * 4099).U(44.W))))
  val ppns = VecInit((0 until entries).map(i => (io.in4(43, 0) ^ (i * 8191).U(44.W))))
  val perms = VecInit((0 until entries).map(i => ((io.in2 >> ((i % 8) * 8))(7, 0) ^ i.U(8.W))))
  val vpn = io.in0(43, 0)
  val asid = io.in1(7, 0)
  val cmd = io.ctrl(2, 0)
  val widx = io.in2(4, 0)
  val refillTag = vpn ^ Cat(0.U(36.W), asid)
  val effTags = VecInit((0 until entries).map(i => Mux(widx === i.U, refillTag, tags(i))))
  val effPpns = VecInit((0 until entries).map(i => Mux(widx === i.U, io.in3(43, 0), ppns(i))))
  val effPerms = VecInit((0 until entries).map(i => Mux(widx === i.U, io.in4(7, 0), perms(i))))
  val hits = VecInit((0 until entries).map(i => effTags(i) === refillTag)).asUInt
  val hitOH = PriorityEncoderOH(hits)
  val hitPerm = Mux1H(hitOH, effPerms)
  val hitPpn = Mux1H(hitOH, effPpns)
  val fault = hits.orR && !MuxLookup(cmd, false.B)(Seq(
    0.U -> hitPerm(0),
    1.U -> hitPerm(1),
    2.U -> hitPerm(2),
    3.U -> (hitPerm(0) && hitPerm(2)),
  ))
  io.out0 := Cat(0.U(32.W), hits)
  io.out1 := Cat(0.U(20.W), hitPpn)
  io.out2 := Cat(0.U(63.W), fault)
  io.out3 := mix64(io.out0, io.out1, 59)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from cache/dcache/meta array read/write and way-hit selection.
class XsDcacheMetaSelectLarge extends XsComponentModule {
  import XsCommon._

  private val sets = 64
  private val ways = 4
  val tags = VecInit((0 until ways).map(w => VecInit((0 until sets).map(s => (io.in3(39, 0) ^ (w * 4099 + s * 257).U(40.W))))))
  val meta = VecInit((0 until ways).map(w => VecInit((0 until sets).map(s => ((io.in4 >> ((s % 8) * 8))(7, 0) ^ (w * 17 + s).U(8.W))))))
  val set = io.in0(5, 0)
  val tag = io.in1(39, 0)
  val wen = io.ctrl(0)
  val wway = io.ctrl(2, 1)
  val effTags = VecInit((0 until ways).map(w => Mux(wen && wway === w.U, tag, tags(w)(set))))
  val effMeta = VecInit((0 until ways).map(w => Mux(wen && wway === w.U, io.in2(7, 0), meta(w)(set))))
  val wayHits = VecInit((0 until ways).map(w => effTags(w) === tag && effMeta(w)(0))).asUInt
  val hitWay = PriorityEncoder(wayHits)
  val replWay = PriorityEncoder(~wayHits(ways - 1, 0))
  val selectedMeta = Mux1H(PriorityEncoderOH(wayHits | UIntToOH(replWay, ways)), effMeta)
  val bankSample = VecInit((0 until 16).map(i => Cat(tags(i % ways)(i.U), meta(i % ways)(i.U)))).reduce(_ ^ _)
  io.out0 := Cat(0.U(60.W), wayHits)
  io.out1 := Cat(0.U(56.W), selectedMeta)
  io.out2 := Cat(0.U(24.W), bankSample(39, 0))
  io.out3 := mix64(Cat(0.U(62.W), hitWay), Cat(0.U(62.W), replWay), 61)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from mem/vector/VMergeBuffer.scala and VSegmentUnit lane mask merge.
class XsVecMergeBufferLarge extends XsComponentModule {
  import XsCommon._

  private val lanes = 16
  val data = VecInit((0 until lanes).map(i => io.in2 ^ rotl(io.in3, (i % 17) + 1) ^ (BigInt(i) * 0x10101).U(64.W)))
  val mask = VecInit((0 until lanes).map(i => ((io.in4 >> ((i % 8) * 8))(7, 0) ^ i.U(8.W))))
  val base = io.in0(3, 0)
  val writeMask = io.ctrl(15, 0)
  val tailMask = io.in1(15, 0)
  def mergeBytes(oldData: UInt, newData: UInt, maskBits: UInt): UInt =
    VecInit((0 until 8).map(i => Mux(maskBits(i), newData(8 * i + 7, 8 * i), oldData(8 * i + 7, 8 * i)))).asUInt
  val dataWire = Wire(Vec(lanes, UInt(64.W)))
  val maskWire = Wire(Vec(lanes, UInt(8.W)))
  for (lane <- 0 until lanes) {
    val hit = writeMask(lane)
    val src = Mux(lane.U < base, io.in2, io.in3) ^ (lane * 0x10101).U
    val mergedData = Mux(hit, mergeBytes(data(lane), src, io.in4(7, 0) ^ lane.U), data(lane))
    val mergedMask = Mux(hit, mask(lane) | (io.in4(7, 0) & Fill(8, !tailMask(lane))), mask(lane))
    dataWire(lane) := mergedData
    maskWire(lane) := mergedMask
  }
  val active = VecInit((0 until lanes).map(i => maskWire(i).orR && !tailMask(i))).asUInt
  val packed = VecInit((0 until lanes).map(i => dataWire(i) ^ Cat(0.U(56.W), maskWire(i)))).reduce(_ ^ _)
  io.out0 := packed
  io.out1 := Cat(0.U(48.W), active)
  io.out2 := Cat(0.U(48.W), writeMask ^ tailMask)
  io.out3 := mix64(io.out0, io.out1, 67)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from mem/prefetch/L1StridePrefetcher.scala stride table update and
// confidence selection.
class XsPrefetchStrideLarge extends XsComponentModule {
  import XsCommon._

  private val entries = 32
  val pcs = RegInit(VecInit(Seq.fill(entries)(0.U(32.W))))
  val lastAddr = RegInit(VecInit(Seq.fill(entries)(0.U(40.W))))
  val stride = RegInit(VecInit(Seq.fill(entries)(0.S(16.W))))
  val conf = RegInit(VecInit(Seq.fill(entries)(0.U(3.W))))
  val pc = io.in0(31, 0)
  val addr = io.in1(39, 0)
  val valid = io.ctrl(0)
  val hits = VecInit((0 until entries).map(i => pcs(i) === pc)).asUInt
  val hitOH = PriorityEncoderOH(hits)
  val hitIdx = PriorityEncoder(hits)
  val replIdx = PriorityEncoder(~hits)
  val idx = Mux(hits.orR, hitIdx, replIdx)
  val newStride = (addr - lastAddr(idx)).asSInt
  when(valid) {
    pcs(idx) := pc
    conf(idx) := Mux(stride(idx) === newStride && conf(idx) =/= 7.U, conf(idx) + 1.U, Mux(conf(idx) === 0.U, 0.U, conf(idx) - 1.U))
    stride(idx) := newStride(15, 0).asSInt
    lastAddr(idx) := addr
  }
  val predicted = (addr.asSInt + stride(idx)).asUInt
  val prefMask = VecInit((0 until entries).map(i => conf(i) > 3.U && pcs(i)(4, 0) === pc(4, 0))).asUInt
  io.out0 := Cat(0.U(32.W), hits)
  io.out1 := Cat(0.U(24.W), predicted(39, 0))
  io.out2 := Cat(0.U(32.W), prefMask)
  io.out3 := mix64(Cat(0.U(59.W), idx), Cat(0.U(61.W), conf(idx)), 71)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from mem/lsqueue/LoadQueueRAW.scala RAW conflict and forwarding
// mask generation.
class XsLoadQueueRawLarge extends XsComponentModule {
  import XsCommon._

  private val entries = 64
  val storeAddr = VecInit((0 until entries).map(i => io.in1(39, 0) ^ (i * 4099).U(40.W)))
  val storeData = VecInit((0 until entries).map(i => io.in2 ^ rotl(io.in3, (i % 17) + 1)))
  val storeMask = VecInit((0 until entries).map { i =>
    val byte = (io.in3 >> ((i % 8) * 8))(7, 0)
    byte ^ i.U(8.W)
  })
  val valid = VecInit((0 until entries).map(i => io.ctrl((i % 31) + 1)))
  val widx = io.in0(5, 0)
  val effAddr = VecInit((0 until entries).map(i => Mux(io.ctrl(0) && widx === i.U, io.in1(39, 0), storeAddr(i))))
  val effData = VecInit((0 until entries).map(i => Mux(io.ctrl(0) && widx === i.U, io.in2, storeData(i))))
  val effMask = VecInit((0 until entries).map(i => Mux(io.ctrl(0) && widx === i.U, io.in3(7, 0), storeMask(i))))
  val effValid = VecInit((0 until entries).map(i => valid(i) || (io.ctrl(0) && widx === i.U)))
  val loadAddr = io.in4(39, 0)
  val loadMask = io.in5(7, 0)
  val rawHits = VecInit((0 until entries).map(i => effValid(i) && effAddr(i)(39, 3) === loadAddr(39, 3) && (effMask(i) & loadMask).orR)).asUInt
  val hitOH = PriorityEncoderOH(rawHits)
  val fwdData = Mux1H(hitOH, effData)
  val merged = VecInit((0 until 8).map(i => Mux(loadMask(i), fwdData(8 * i + 7, 8 * i), io.in2(8 * i + 7, 8 * i)))).asUInt
  io.out0 := rawHits
  io.out1 := fwdData
  io.out2 := merged
  io.out3 := mix64(Cat(0.U(57.W), PopCount(rawHits)), Cat(0.U(56.W), loadMask), 73)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

// Extracted from backend/fu/NewCSR interrupt and trap priority selection.
class XsCsrTrapPriorityLarge extends XsComponentModule {
  import XsCommon._

  private val sources = 32
  val pending = (io.in0(31, 0) | io.ctrl(31, 0)) & ~io.in1(31, 0)
  val enable = io.in2(31, 0)
  val deleg = io.in3(31, 0)
  val active = pending & enable
  val machine = active & ~deleg
  val supervisor = active & deleg
  val mOh = Reverse(PriorityEncoderOH(Reverse(machine)))
  val sOh = Reverse(PriorityEncoderOH(Reverse(supervisor)))
  val chooseM = machine.orR || !supervisor.orR
  val cause = Mux(chooseM, mOh, sOh)
  val trapVec = VecInit((0 until sources).map(i => active(i) && (i.U >= io.ctrl(10, 6)))).asUInt
  io.out0 := Cat(0.U(32.W), active)
  io.out1 := Cat(0.U(32.W), machine)
  io.out2 := Cat(0.U(32.W), supervisor)
  io.out3 := mix64(Cat(0.U(32.W), cause), Cat(0.U(32.W), trapVec), 79)
  io.flags := io.out0 ^ io.out1 ^ io.out2 ^ io.out3 ^ io.ctrl
  io.checksum := fold(Seq(io.out0, io.out1, io.out2, io.out3, io.flags))
}

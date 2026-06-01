package xscomponents

import chisel3.RawModule
import chisel3.stage.ChiselGeneratorAnnotation
import _root_.circt.stage.ChiselStage
import _root_.circt.stage.FirtoolOption

object XsComponentsMain extends App {
  val tops = Map[String, () => RawModule](
    "XsBranchAluSmall" -> (() => new XsBranchAluSmall),
    "XsVectorMaskMedium" -> (() => new XsVectorMaskMedium),
    "XsAgeMatrixMedium" -> (() => new XsAgeMatrixMedium),
    "XsPlruLarge" -> (() => new XsPlruLarge),
    "XsStoreMergeLarge" -> (() => new XsStoreMergeLarge),
    "XsIcacheReplacerLarge" -> (() => new XsIcacheReplacerLarge),
    "XsIcacheReplRegsLarge" -> (() => new XsIcacheReplRegsLarge),
    "XsIcacheReplRegsDiscreteLarge" -> (() => new XsIcacheReplRegsDiscreteLarge),
    "XsIcacheReplRegsCatLarge" -> (() => new XsIcacheReplRegsCatLarge),
    "XsStoreQueueBanksLarge" -> (() => new XsStoreQueueBanksLarge),
    "XsLoadQueueReplayLarge" -> (() => new XsLoadQueueReplayLarge),
    "XsPlruBankedXLarge" -> (() => new XsPlruBankedXLarge),
    "XsFreeListAllocLarge" -> (() => new XsFreeListAllocLarge),
    "XsRobBankScanLarge" -> (() => new XsRobBankScanLarge),
    "XsIssueBusyMaskLarge" -> (() => new XsIssueBusyMaskLarge),
    "XsWbArbiterLarge" -> (() => new XsWbArbiterLarge),
    "XsFusionDecodeLarge" -> (() => new XsFusionDecodeLarge),
    "XsTlbPermLarge" -> (() => new XsTlbPermLarge),
    "XsDcacheMetaSelectLarge" -> (() => new XsDcacheMetaSelectLarge),
    "XsVecMergeBufferLarge" -> (() => new XsVecMergeBufferLarge),
    "XsPrefetchStrideLarge" -> (() => new XsPrefetchStrideLarge),
    "XsLoadQueueRawLarge" -> (() => new XsLoadQueueRawLarge),
    "XsCsrTrapPriorityLarge" -> (() => new XsCsrTrapPriorityLarge),
  )

  val top = args.sliding(2).collectFirst { case Array("--top-name", name) => name }.getOrElse("XsBranchAluSmall")
  val filteredArgs = args.toSeq.sliding(2).foldLeft(args.toSeq) {
    case (acc, Seq("--top-name", name)) => acc.filterNot(x => x == "--top-name" || x == name)
    case (acc, _) => acc
  }
  val gen = tops.getOrElse(top, sys.error(s"unknown xs-component top '$top'"))
  (new ChiselStage).execute(
    filteredArgs.toArray,
    Seq(
      ChiselGeneratorAnnotation(gen),
      FirtoolOption("--disable-all-randomization"),
    ),
  )
}

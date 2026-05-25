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
    "XsStoreQueueBanksLarge" -> (() => new XsStoreQueueBanksLarge),
    "XsLoadQueueReplayLarge" -> (() => new XsLoadQueueReplayLarge),
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
      FirtoolOption("--preserve-aggregate=1d-vec"),
    ),
  )
}

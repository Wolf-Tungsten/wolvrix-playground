SHELL := /bin/bash

PYTHON ?= python3
CXX = clang++
MILL ?= mill
GSIM_BIN ?= ../../reference/gsim/build/gsim/gsim
OBJDUMP ?= objdump
CACHE_DIR ?= .sandbox-cache
MILL_ENV := COURSIER_CACHE=$(abspath $(CACHE_DIR)/coursier) XDG_CACHE_HOME=$(abspath $(CACHE_DIR)/xdg) IVY_HOME=$(abspath $(CACHE_DIR)/ivy2) MILL_COURSIER_CACHE=$(abspath $(CACHE_DIR)/mill-coursier)

CASES := XsReal000PipelineLoadunitLarge XsReal001RobRobLarge XsReal002MemMemblockLarge XsReal003DecodeDecodeunitcompLarge XsReal004LsqueueStorequeueLarge XsReal005MmuPagetablecacheLarge XsReal006DcacheDcachewrapperLarge XsReal007FuCsrLarge XsReal008DecodeDecodeunitLarge XsReal009NewcsrNewcsrLarge XsReal010IssueIssuequeueLarge XsReal011MainpipeMissqueueLarge XsReal012MmuPagetablewalkerLarge XsReal013PrefetchSmsprefetcherLarge XsReal014DispatchNewdispatchLarge XsReal015Tl2ChiMshrLarge XsReal016DecodeVecdecoderLarge XsReal017MmuL2TlbLarge XsReal018VectorVsegmentunitLarge XsReal019BackendCtrlblockLarge XsReal020DatapathDatapathLarge XsReal021Tl2ChiMainpipeLarge XsReal022BackendRegionLarge XsReal023RenameRenameLarge XsReal024MainpipeMainpipeLarge XsReal025IfuIfuLarge XsReal026LsqueueLoadqueuereplayLarge XsReal027SbufferSbufferLarge XsReal028PrefetchL1PrefetchcomponentLarge XsReal029PipelineStoreunitLarge XsReal030PrefetchBertiLarge XsReal031DataBankeddataarrayLarge XsReal032IssueEntriesLarge XsReal033XiangshanPackageLarge XsReal034MmuTlbLarge XsReal035BackendBackendLarge XsReal036VectorVeccommonLarge XsReal037Tl2TlMainpipeLarge XsReal038PrefetchBestoffsetprefetchLarge XsReal039LoadpipeLoadpipeLarge XsReal040MmuRepeaterLarge XsReal041ScScLarge XsReal042ExuExeunitLarge XsReal043TageTageLarge XsReal044SramSramtemplateLarge XsReal045NewcsrMachinelevelLarge XsReal046PipelineAtomicsunitLarge XsReal047LsqueueLoadmisalignbufferLarge XsReal048LsqueueStoremisalignbufferLarge XsReal049LsqueueLsqwrapperLarge XsReal050Coupledl2Coupledl2Large XsReal051DcacheUncacheLarge XsReal052WrapperCsrLarge XsReal053FtqFtqLarge XsReal054VectorVsplitLarge XsReal055DecodeFusiondecoderLarge XsReal056IcacheIcacheprefetchpipeLarge XsReal057BpuBpuLarge XsReal058LsqueueLoadqueueuncacheLarge XsReal059VectorVmergebufferLarge XsReal060MdpStoresetLarge XsReal061UtilityChiseltaggedtraceLarge XsReal062MmuBitmapcheckLarge XsReal063LsqueueLoadqueuerawLarge XsReal064IcacheIcachemissunitLarge XsReal065NewcsrCsrpermitmoduleLarge XsReal066LsqueueLoadqueueLarge XsReal067DatapathWbarbiterLarge XsReal068Tl2TlMshrLarge XsReal069IbufferIbufferLarge XsReal070PrefetchL1StreamprefetcherLarge XsReal071IcacheIcachemainpipeLarge XsReal072BackendVecexcpdatamergemoduleLarge XsReal073PrefetchPrefetcherwrapperLarge XsReal074DatapathBypassnetworkLarge XsReal075RobVtypebufferLarge XsReal076Coupledl2GrantbufferLarge XsReal077RegfileRegfileLarge XsReal078WrapperVfaluLarge XsReal079PrefetchPrefetcherLarge XsReal080XiangshanL2TopLarge XsReal081RenameRenametableLarge XsReal082Tl2ChiMmiobridgeLarge XsReal083ChiMessageLarge XsReal084IttageIttageLarge XsReal085MainpipeWritebackqueueLarge XsReal086DecodeDecodestageLarge XsReal087NewcsrInterruptfilterLarge XsReal088FuPmpLarge XsReal089LsqueueStorequeuedataLarge XsReal090PrefetchTemporalprefetchLarge XsReal091Coupledl2RequestbufferLarge XsReal092MmuTlbstorageLarge XsReal093FrontendFrontendLarge XsReal094Coupledl2RequestarbLarge XsReal095RobRabLarge XsReal096Coupledl2CommonLarge XsReal097FuSrt16DividerLarge XsReal098LsqueueVirtualloadqueueLarge XsReal099PrefetchPrefetchermonitorLarge XsReal100BackendNfmappedelemidxSmall
KIND_XsReal000PipelineLoadunitLarge := mem-pipeline-loadunit
KIND_XsReal001RobRobLarge := backend-rob-rob
KIND_XsReal002MemMemblockLarge := mem-memblock
KIND_XsReal003DecodeDecodeunitcompLarge := backend-decode-decodeunitcomp
KIND_XsReal004LsqueueStorequeueLarge := mem-lsqueue-storequeue
KIND_XsReal005MmuPagetablecacheLarge := cache-mmu-pagetablecache
KIND_XsReal006DcacheDcachewrapperLarge := cache-dcache-dcachewrapper
KIND_XsReal007FuCsrLarge := backend-fu-csr
KIND_XsReal008DecodeDecodeunitLarge := backend-decode-decodeunit
KIND_XsReal009NewcsrNewcsrLarge := backend-fu-newcsr-newcsr
KIND_XsReal010IssueIssuequeueLarge := backend-issue-issuequeue
KIND_XsReal011MainpipeMissqueueLarge := cache-dcache-mainpipe-missqueue
KIND_XsReal012MmuPagetablewalkerLarge := cache-mmu-pagetablewalker
KIND_XsReal013PrefetchSmsprefetcherLarge := mem-prefetch-smsprefetcher
KIND_XsReal014DispatchNewdispatchLarge := backend-dispatch-newdispatch
KIND_XsReal015Tl2ChiMshrLarge := coupledl2-src-main-scala-coupledl2-tl2chi-mshr
KIND_XsReal016DecodeVecdecoderLarge := backend-decode-vecdecoder
KIND_XsReal017MmuL2TlbLarge := cache-mmu-l2tlb
KIND_XsReal018VectorVsegmentunitLarge := mem-vector-vsegmentunit
KIND_XsReal019BackendCtrlblockLarge := backend-ctrlblock
KIND_XsReal020DatapathDatapathLarge := backend-datapath-datapath
KIND_XsReal021Tl2ChiMainpipeLarge := coupledl2-src-main-scala-coupledl2-tl2chi-mainpipe
KIND_XsReal022BackendRegionLarge := backend-region
KIND_XsReal023RenameRenameLarge := backend-rename-rename
KIND_XsReal024MainpipeMainpipeLarge := cache-dcache-mainpipe-mainpipe
KIND_XsReal025IfuIfuLarge := frontend-ifu-ifu
KIND_XsReal026LsqueueLoadqueuereplayLarge := mem-lsqueue-loadqueuereplay
KIND_XsReal027SbufferSbufferLarge := mem-sbuffer-sbuffer
KIND_XsReal028PrefetchL1PrefetchcomponentLarge := mem-prefetch-l1prefetchcomponent
KIND_XsReal029PipelineStoreunitLarge := mem-pipeline-storeunit
KIND_XsReal030PrefetchBertiLarge := mem-prefetch-berti
KIND_XsReal031DataBankeddataarrayLarge := cache-dcache-data-bankeddataarray
KIND_XsReal032IssueEntriesLarge := backend-issue-entries
KIND_XsReal033XiangshanPackageLarge := xiangshan-package
KIND_XsReal034MmuTlbLarge := cache-mmu-tlb
KIND_XsReal035BackendBackendLarge := backend-backend
KIND_XsReal036VectorVeccommonLarge := mem-vector-veccommon
KIND_XsReal037Tl2TlMainpipeLarge := coupledl2-src-main-scala-coupledl2-tl2tl-mainpipe
KIND_XsReal038PrefetchBestoffsetprefetchLarge := coupledl2-src-main-scala-coupledl2-prefetch-bestoffsetprefetch
KIND_XsReal039LoadpipeLoadpipeLarge := cache-dcache-loadpipe-loadpipe
KIND_XsReal040MmuRepeaterLarge := cache-mmu-repeater
KIND_XsReal041ScScLarge := frontend-bpu-sc-sc
KIND_XsReal042ExuExeunitLarge := backend-exu-exeunit
KIND_XsReal043TageTageLarge := frontend-bpu-tage-tage
KIND_XsReal044SramSramtemplateLarge := utility-src-main-scala-utility-sram-sramtemplate
KIND_XsReal045NewcsrMachinelevelLarge := backend-fu-newcsr-machinelevel
KIND_XsReal046PipelineAtomicsunitLarge := mem-pipeline-atomicsunit
KIND_XsReal047LsqueueLoadmisalignbufferLarge := mem-lsqueue-loadmisalignbuffer
KIND_XsReal048LsqueueStoremisalignbufferLarge := mem-lsqueue-storemisalignbuffer
KIND_XsReal049LsqueueLsqwrapperLarge := mem-lsqueue-lsqwrapper
KIND_XsReal050Coupledl2Coupledl2Large := coupledl2-src-main-scala-coupledl2-coupledl2
KIND_XsReal051DcacheUncacheLarge := cache-dcache-uncache
KIND_XsReal052WrapperCsrLarge := backend-fu-wrapper-csr
KIND_XsReal053FtqFtqLarge := frontend-ftq-ftq
KIND_XsReal054VectorVsplitLarge := mem-vector-vsplit
KIND_XsReal055DecodeFusiondecoderLarge := backend-decode-fusiondecoder
KIND_XsReal056IcacheIcacheprefetchpipeLarge := frontend-icache-icacheprefetchpipe
KIND_XsReal057BpuBpuLarge := frontend-bpu-bpu
KIND_XsReal058LsqueueLoadqueueuncacheLarge := mem-lsqueue-loadqueueuncache
KIND_XsReal059VectorVmergebufferLarge := mem-vector-vmergebuffer
KIND_XsReal060MdpStoresetLarge := mem-mdp-storeset
KIND_XsReal061UtilityChiseltaggedtraceLarge := utility-src-main-scala-utility-chiseltaggedtrace
KIND_XsReal062MmuBitmapcheckLarge := cache-mmu-bitmapcheck
KIND_XsReal063LsqueueLoadqueuerawLarge := mem-lsqueue-loadqueueraw
KIND_XsReal064IcacheIcachemissunitLarge := frontend-icache-icachemissunit
KIND_XsReal065NewcsrCsrpermitmoduleLarge := backend-fu-newcsr-csrpermitmodule
KIND_XsReal066LsqueueLoadqueueLarge := mem-lsqueue-loadqueue
KIND_XsReal067DatapathWbarbiterLarge := backend-datapath-wbarbiter
KIND_XsReal068Tl2TlMshrLarge := coupledl2-src-main-scala-coupledl2-tl2tl-mshr
KIND_XsReal069IbufferIbufferLarge := frontend-ibuffer-ibuffer
KIND_XsReal070PrefetchL1StreamprefetcherLarge := mem-prefetch-l1streamprefetcher
KIND_XsReal071IcacheIcachemainpipeLarge := frontend-icache-icachemainpipe
KIND_XsReal072BackendVecexcpdatamergemoduleLarge := backend-vecexcpdatamergemodule
KIND_XsReal073PrefetchPrefetcherwrapperLarge := mem-prefetch-prefetcherwrapper
KIND_XsReal074DatapathBypassnetworkLarge := backend-datapath-bypassnetwork
KIND_XsReal075RobVtypebufferLarge := backend-rob-vtypebuffer
KIND_XsReal076Coupledl2GrantbufferLarge := coupledl2-src-main-scala-coupledl2-grantbuffer
KIND_XsReal077RegfileRegfileLarge := backend-regfile-regfile
KIND_XsReal078WrapperVfaluLarge := backend-fu-wrapper-vfalu
KIND_XsReal079PrefetchPrefetcherLarge := coupledl2-src-main-scala-coupledl2-prefetch-prefetcher
KIND_XsReal080XiangshanL2TopLarge := xiangshan-l2top
KIND_XsReal081RenameRenametableLarge := backend-rename-renametable
KIND_XsReal082Tl2ChiMmiobridgeLarge := coupledl2-src-main-scala-coupledl2-tl2chi-mmiobridge
KIND_XsReal083ChiMessageLarge := coupledl2-src-main-scala-coupledl2-tl2chi-chi-message
KIND_XsReal084IttageIttageLarge := frontend-bpu-ittage-ittage
KIND_XsReal085MainpipeWritebackqueueLarge := cache-dcache-mainpipe-writebackqueue
KIND_XsReal086DecodeDecodestageLarge := backend-decode-decodestage
KIND_XsReal087NewcsrInterruptfilterLarge := backend-fu-newcsr-interruptfilter
KIND_XsReal088FuPmpLarge := backend-fu-pmp
KIND_XsReal089LsqueueStorequeuedataLarge := mem-lsqueue-storequeuedata
KIND_XsReal090PrefetchTemporalprefetchLarge := coupledl2-src-main-scala-coupledl2-prefetch-temporalprefetch
KIND_XsReal091Coupledl2RequestbufferLarge := coupledl2-src-main-scala-coupledl2-requestbuffer
KIND_XsReal092MmuTlbstorageLarge := cache-mmu-tlbstorage
KIND_XsReal093FrontendFrontendLarge := frontend-frontend
KIND_XsReal094Coupledl2RequestarbLarge := coupledl2-src-main-scala-coupledl2-requestarb
KIND_XsReal095RobRabLarge := backend-rob-rab
KIND_XsReal096Coupledl2CommonLarge := coupledl2-src-main-scala-coupledl2-common
KIND_XsReal097FuSrt16DividerLarge := backend-fu-srt16divider
KIND_XsReal098LsqueueVirtualloadqueueLarge := mem-lsqueue-virtualloadqueue
KIND_XsReal099PrefetchPrefetchermonitorLarge := mem-prefetch-prefetchermonitor
KIND_XsReal100BackendNfmappedelemidxSmall := backend-nfmappedelemidx
SCALE_XsReal000PipelineLoadunitLarge := large
SCALE_XsReal001RobRobLarge := large
SCALE_XsReal002MemMemblockLarge := large
SCALE_XsReal003DecodeDecodeunitcompLarge := large
SCALE_XsReal004LsqueueStorequeueLarge := large
SCALE_XsReal005MmuPagetablecacheLarge := large
SCALE_XsReal006DcacheDcachewrapperLarge := large
SCALE_XsReal007FuCsrLarge := large
SCALE_XsReal008DecodeDecodeunitLarge := large
SCALE_XsReal009NewcsrNewcsrLarge := large
SCALE_XsReal010IssueIssuequeueLarge := large
SCALE_XsReal011MainpipeMissqueueLarge := large
SCALE_XsReal012MmuPagetablewalkerLarge := large
SCALE_XsReal013PrefetchSmsprefetcherLarge := large
SCALE_XsReal014DispatchNewdispatchLarge := large
SCALE_XsReal015Tl2ChiMshrLarge := large
SCALE_XsReal016DecodeVecdecoderLarge := large
SCALE_XsReal017MmuL2TlbLarge := large
SCALE_XsReal018VectorVsegmentunitLarge := large
SCALE_XsReal019BackendCtrlblockLarge := large
SCALE_XsReal020DatapathDatapathLarge := large
SCALE_XsReal021Tl2ChiMainpipeLarge := large
SCALE_XsReal022BackendRegionLarge := large
SCALE_XsReal023RenameRenameLarge := large
SCALE_XsReal024MainpipeMainpipeLarge := large
SCALE_XsReal025IfuIfuLarge := large
SCALE_XsReal026LsqueueLoadqueuereplayLarge := large
SCALE_XsReal027SbufferSbufferLarge := large
SCALE_XsReal028PrefetchL1PrefetchcomponentLarge := large
SCALE_XsReal029PipelineStoreunitLarge := large
SCALE_XsReal030PrefetchBertiLarge := large
SCALE_XsReal031DataBankeddataarrayLarge := large
SCALE_XsReal032IssueEntriesLarge := large
SCALE_XsReal033XiangshanPackageLarge := large
SCALE_XsReal034MmuTlbLarge := large
SCALE_XsReal035BackendBackendLarge := large
SCALE_XsReal036VectorVeccommonLarge := large
SCALE_XsReal037Tl2TlMainpipeLarge := large
SCALE_XsReal038PrefetchBestoffsetprefetchLarge := large
SCALE_XsReal039LoadpipeLoadpipeLarge := large
SCALE_XsReal040MmuRepeaterLarge := large
SCALE_XsReal041ScScLarge := large
SCALE_XsReal042ExuExeunitLarge := large
SCALE_XsReal043TageTageLarge := large
SCALE_XsReal044SramSramtemplateLarge := large
SCALE_XsReal045NewcsrMachinelevelLarge := large
SCALE_XsReal046PipelineAtomicsunitLarge := large
SCALE_XsReal047LsqueueLoadmisalignbufferLarge := large
SCALE_XsReal048LsqueueStoremisalignbufferLarge := large
SCALE_XsReal049LsqueueLsqwrapperLarge := large
SCALE_XsReal050Coupledl2Coupledl2Large := large
SCALE_XsReal051DcacheUncacheLarge := large
SCALE_XsReal052WrapperCsrLarge := large
SCALE_XsReal053FtqFtqLarge := large
SCALE_XsReal054VectorVsplitLarge := large
SCALE_XsReal055DecodeFusiondecoderLarge := large
SCALE_XsReal056IcacheIcacheprefetchpipeLarge := large
SCALE_XsReal057BpuBpuLarge := large
SCALE_XsReal058LsqueueLoadqueueuncacheLarge := large
SCALE_XsReal059VectorVmergebufferLarge := large
SCALE_XsReal060MdpStoresetLarge := large
SCALE_XsReal061UtilityChiseltaggedtraceLarge := large
SCALE_XsReal062MmuBitmapcheckLarge := large
SCALE_XsReal063LsqueueLoadqueuerawLarge := large
SCALE_XsReal064IcacheIcachemissunitLarge := large
SCALE_XsReal065NewcsrCsrpermitmoduleLarge := large
SCALE_XsReal066LsqueueLoadqueueLarge := large
SCALE_XsReal067DatapathWbarbiterLarge := large
SCALE_XsReal068Tl2TlMshrLarge := large
SCALE_XsReal069IbufferIbufferLarge := large
SCALE_XsReal070PrefetchL1StreamprefetcherLarge := large
SCALE_XsReal071IcacheIcachemainpipeLarge := large
SCALE_XsReal072BackendVecexcpdatamergemoduleLarge := large
SCALE_XsReal073PrefetchPrefetcherwrapperLarge := large
SCALE_XsReal074DatapathBypassnetworkLarge := large
SCALE_XsReal075RobVtypebufferLarge := large
SCALE_XsReal076Coupledl2GrantbufferLarge := large
SCALE_XsReal077RegfileRegfileLarge := large
SCALE_XsReal078WrapperVfaluLarge := large
SCALE_XsReal079PrefetchPrefetcherLarge := large
SCALE_XsReal080XiangshanL2TopLarge := large
SCALE_XsReal081RenameRenametableLarge := large
SCALE_XsReal082Tl2ChiMmiobridgeLarge := large
SCALE_XsReal083ChiMessageLarge := large
SCALE_XsReal084IttageIttageLarge := large
SCALE_XsReal085MainpipeWritebackqueueLarge := large
SCALE_XsReal086DecodeDecodestageLarge := large
SCALE_XsReal087NewcsrInterruptfilterLarge := large
SCALE_XsReal088FuPmpLarge := large
SCALE_XsReal089LsqueueStorequeuedataLarge := large
SCALE_XsReal090PrefetchTemporalprefetchLarge := large
SCALE_XsReal091Coupledl2RequestbufferLarge := large
SCALE_XsReal092MmuTlbstorageLarge := large
SCALE_XsReal093FrontendFrontendLarge := large
SCALE_XsReal094Coupledl2RequestarbLarge := large
SCALE_XsReal095RobRabLarge := large
SCALE_XsReal096Coupledl2CommonLarge := large
SCALE_XsReal097FuSrt16DividerLarge := large
SCALE_XsReal098LsqueueVirtualloadqueueLarge := large
SCALE_XsReal099PrefetchPrefetchermonitorLarge := large
SCALE_XsReal100BackendNfmappedelemidxSmall := small

CASE ?= XsReal000PipelineLoadunitLarge
KIND := $(KIND_$(CASE))
SCALE := $(SCALE_$(CASE))
BUILD_DIR ?= build
CASE_BUILD := $(BUILD_DIR)/$(CASE)
FIR_DIR := $(CASE_BUILD)/chisel-fir
SV_DIR := $(CASE_BUILD)/chisel-sv
GSIM_DIR := $(CASE_BUILD)/gsim
GRHSIM_DIR := $(CASE_BUILD)/grhsim
GRHSIM_AM_DIR := $(CASE_BUILD)/grhsim-am
GRHSIM_AM_NORMALIZE_DIR := $(GRHSIM_AM_DIR)/normalize
GSIM_MODEL_DIR := $(GSIM_DIR)/model
GRHSIM_MODEL_DIR := $(GRHSIM_DIR)/model
GRHSIM_AM_MODEL_DIR := $(GRHSIM_AM_DIR)/model
TB_DIR := $(CASE_BUILD)/tb
STATS_DIR := $(CASE_BUILD)/stats
MATRIX_DIR := $(BUILD_DIR)/matrix

FIR := $(FIR_DIR)/$(CASE).fir
SV := $(SV_DIR)/$(CASE).sv
GSIM_GRAPH_STATS := $(GSIM_MODEL_DIR)/$(CASE)_0Final_Stats.json
GRHSIM_GRAPH_STATS := $(GRHSIM_MODEL_DIR)/activity_schedule_stats.json
GRHSIM_AM_PRE_SCHEDULE_JSON := $(GRHSIM_AM_NORMALIZE_DIR)/$(CASE).json
GSIM_BUILD_STAMP := $(GSIM_DIR)/obj/.stamp
GRHSIM_LIB := $(GRHSIM_MODEL_DIR)/libgrhsim_$(CASE).a
GRHSIM_AM_LIB := $(GRHSIM_AM_MODEL_DIR)/libgrhsim_$(CASE).a
BENCH_TB := $(TB_DIR)/$(CASE)_bench
BENCH_LOG := $(TB_DIR)/$(CASE)_bench.log
GSIM_PORT_WIDTHS_HEADER := $(TB_DIR)/gsim_port_widths.hpp
MODEL_STATS_JSON := $(STATS_DIR)/model_stats.json

GSIM_FLAGS ?= --supernode-max-size=8 --cpp-max-size-KB=512
GSIM_CXXFLAGS ?= -O3 -std=c++17 -fbracket-depth=2048 -Wno-parentheses-equality -I$(abspath $(GSIM_MODEL_DIR))
GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE ?= 128
GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE ?= 768
GRHSIM_SCHED_BATCH_MAX_OPS ?= 2048
GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES ?= 8192
GRHSIM_SCHED_BATCH_TARGET_COUNT ?= 64
GRHSIM_EMIT_PARALLELISM ?= 4
GRHSIM_PERF ?= off
GRHSIM_INPUT_FULLPASS_SPECIALIZATION ?= 0
GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION ?= 0
GRHSIM_CXXFLAGS ?= -O3 -std=c++20
GRHSIM_AM_LOWER_JSON ?= ../../wolvrix/build/bin/grhsim-am-lower-json
GRHSIM_AM_BLOCKS_PER_SOURCE ?= 2048
GRHSIM_AM_MAX_SOURCE_BYTES ?= 4194304
GRHSIM_AM_MAX_ATOMS_PER_BLOCK ?= 128
GRHSIM_AM_DP_SEGMENT_PENALTY ?= 1
GRHSIM_AM_DP_COARSEN_ATOM_BUDGET ?= 0
GRHSIM_AM_CXXFLAGS ?= $(GRHSIM_CXXFLAGS)
BENCH_CXXFLAGS ?= -O3 -std=c++20 -I$(abspath $(GSIM_MODEL_DIR)) -I$(abspath $(GRHSIM_MODEL_DIR))
BENCH_VECTORS ?= 100000
BENCH_VERIFY ?= 2048
BENCH_REPEAT ?= 1

.PHONY: all generate chisel-fir chisel-sv gsim grhsim grhsim-am grhsim-am-emit grhsim-am-build bench stats stat one matrix clean list

all: matrix

list:
	@printf '%s\n' $(CASES)

generate: $(FIR) $(SV)

SCALA_SRCS := $(shell find src/main/scala -name '*.scala' | sort)

$(FIR): $(SCALA_SRCS) build.mill
	@mkdir -p $(FIR_DIR) $(CACHE_DIR)/coursier $(CACHE_DIR)/xdg $(CACHE_DIR)/ivy2 $(CACHE_DIR)/mill-coursier
	$(MILL_ENV) $(MILL) --no-daemon xscomponents.runMain xscomponents.XsComponentsMain --top-name $(CASE) --target chirrtl --target-dir $(FIR_DIR)
	test -f $@

$(SV): $(SCALA_SRCS) build.mill
	@mkdir -p $(SV_DIR) $(CACHE_DIR)/coursier $(CACHE_DIR)/xdg $(CACHE_DIR)/ivy2 $(CACHE_DIR)/mill-coursier
	$(MILL_ENV) $(MILL) --no-daemon xscomponents.runMain xscomponents.XsComponentsMain --top-name $(CASE) --target systemverilog --target-dir $(SV_DIR) --split-verilog
	test -f $@

chisel-fir: $(FIR)

chisel-sv: $(SV)

$(GSIM_MODEL_DIR)/$(CASE)0.cpp $(GSIM_MODEL_DIR)/$(CASE).h $(GSIM_GRAPH_STATS) &: $(FIR) $(GSIM_BIN)
	@mkdir -p $(GSIM_MODEL_DIR)
	set -o pipefail; $(GSIM_BIN) $(GSIM_FLAGS) --dump-stats-json --dump-stages=Final --dir $(GSIM_MODEL_DIR) $(FIR) | tee $(GSIM_DIR)/gsim.log
	test -f $(GSIM_MODEL_DIR)/$(CASE)0.cpp
	test -f $(GSIM_MODEL_DIR)/$(CASE).h
	test -f $(GSIM_GRAPH_STATS)

$(GSIM_BUILD_STAMP): $(GSIM_MODEL_DIR)/$(CASE)0.cpp
	@mkdir -p $(GSIM_DIR)/obj
	@for src in $(GSIM_MODEL_DIR)/*.cpp; do \
		obj="$(GSIM_DIR)/obj/$$(basename "$${src%.cpp}").o"; \
		echo "+ CXX $$src"; \
		$(CXX) $(GSIM_CXXFLAGS) -c "$$src" -o "$$obj" || exit $$?; \
	done
	@touch $@

gsim: $(GSIM_BUILD_STAMP)

$(GRHSIM_MODEL_DIR)/Makefile $(GRHSIM_GRAPH_STATS) &: $(SV) scripts/emit_grhsim.py
	@mkdir -p $(GRHSIM_MODEL_DIR)
	$(PYTHON) scripts/emit_grhsim.py --sv $(SV) --top $(CASE) --out $(GRHSIM_MODEL_DIR) --json $(GRHSIM_DIR)/$(CASE).json \
		--max-op-in-compute-supernode $(GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE) \
		--max-op-in-commit-supernode $(GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE) \
		--sched-batch-max-ops $(GRHSIM_SCHED_BATCH_MAX_OPS) \
		--sched-batch-max-estimated-lines $(GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES) \
		--sched-batch-target-count $(GRHSIM_SCHED_BATCH_TARGET_COUNT) \
		--emit-parallelism $(GRHSIM_EMIT_PARALLELISM) \
		--perf $(GRHSIM_PERF) \
		$(if $(filter 1 true TRUE yes YES on ON,$(GRHSIM_INPUT_FULLPASS_SPECIALIZATION)),--input-fullpass-specialization,) \
		$(if $(filter 1 true TRUE yes YES on ON,$(GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION)),--posedge-fullpass-specialization,)
	test -f $(GRHSIM_MODEL_DIR)/Makefile
	test -f $(GRHSIM_GRAPH_STATS)

$(GRHSIM_LIB): $(GRHSIM_MODEL_DIR)/Makefile
	$(MAKE) -C $(GRHSIM_MODEL_DIR) CXX=$(CXX) CXXFLAGS="$(GRHSIM_CXXFLAGS)"

grhsim: $(GRHSIM_LIB)

$(GRHSIM_AM_PRE_SCHEDULE_JSON): $(SV) scripts/emit_grhsim.py
	@mkdir -p $(GRHSIM_AM_NORMALIZE_DIR)
	$(PYTHON) scripts/emit_grhsim.py --sv $(SV) --top $(CASE) --out $(GRHSIM_AM_NORMALIZE_DIR) \
		--pre-schedule-json $@ --stop-after-pre-schedule
	test -f $@

$(GRHSIM_AM_MODEL_DIR)/Makefile: $(GRHSIM_AM_PRE_SCHEDULE_JSON) $(GRHSIM_AM_LOWER_JSON)
	@mkdir -p $(GRHSIM_AM_MODEL_DIR)
	set -o pipefail; $(GRHSIM_AM_LOWER_JSON) $(GRHSIM_AM_PRE_SCHEDULE_JSON) $(CASE) \
		--emit $(GRHSIM_AM_MODEL_DIR) \
		--blocks-per-source $(GRHSIM_AM_BLOCKS_PER_SOURCE) \
		--max-source-bytes $(GRHSIM_AM_MAX_SOURCE_BYTES) \
		--max-atoms-per-block $(GRHSIM_AM_MAX_ATOMS_PER_BLOCK) \
		--dp-segment-penalty $(GRHSIM_AM_DP_SEGMENT_PENALTY) \
		--dp-coarsen-atom-budget $(GRHSIM_AM_DP_COARSEN_ATOM_BUDGET) \
		2>&1 | tee $(GRHSIM_AM_DIR)/lower.log
	test -f $(GRHSIM_AM_MODEL_DIR)/Makefile
	test -f $(GRHSIM_AM_MODEL_DIR)/grhsim_$(CASE).hpp

grhsim-am-emit: $(GRHSIM_AM_MODEL_DIR)/Makefile

$(GRHSIM_AM_LIB): $(GRHSIM_AM_MODEL_DIR)/Makefile
	$(MAKE) -C $(GRHSIM_AM_MODEL_DIR) CXX=$(CXX) CXXFLAGS="$(GRHSIM_AM_CXXFLAGS)"

grhsim-am grhsim-am-build: $(GRHSIM_AM_LIB)

$(GSIM_PORT_WIDTHS_HEADER): $(GSIM_MODEL_DIR)/$(CASE).h scripts/gsim_port_widths.py
	@mkdir -p $(TB_DIR)
	$(PYTHON) scripts/gsim_port_widths.py --header $(GSIM_MODEL_DIR)/$(CASE).h --out $@

$(BENCH_TB): tb/xs_component_bench.cpp tb/xs_component_bench.hpp $(GSIM_PORT_WIDTHS_HEADER) $(GSIM_BUILD_STAMP) $(GRHSIM_LIB)
	@mkdir -p $(TB_DIR)
	$(CXX) $(BENCH_CXXFLAGS) -I$(abspath tb) \
		-include $(abspath $(GSIM_PORT_WIDTHS_HEADER)) \
		-DTOP_NAME=\"$(CASE)\" \
		-DGSIM_CLASS=S$(CASE) \
		-DGRHSIM_CLASS=GrhSIM_$(CASE) \
		-DTOP_HEADER=\"$(CASE).h\" \
		-DGRHSIM_HEADER=\"grhsim_$(CASE).hpp\" \
		tb/xs_component_bench.cpp \
		$(GSIM_DIR)/obj/*.o \
		$(GRHSIM_LIB) \
		-o $@

bench: $(BENCH_TB)
	@mkdir -p $(TB_DIR)
	set -o pipefail; $(BENCH_TB) --vectors $(BENCH_VECTORS) --verify $(BENCH_VERIFY) --repeat $(BENCH_REPEAT) 2>&1 | tee $(BENCH_LOG)

$(STATS_DIR)/gsim.json: $(GSIM_BUILD_STAMP) scripts/objdump_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/objdump_stats.py --label gsim --out $@ --objdump $(OBJDUMP) $(GSIM_DIR)/obj/*.o

$(STATS_DIR)/grhsim.json: $(GRHSIM_LIB) scripts/objdump_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/objdump_stats.py --label grhsim --out $@ --objdump $(OBJDUMP) $(GRHSIM_MODEL_DIR)/*.o

stats: $(STATS_DIR)/gsim.json $(STATS_DIR)/grhsim.json

$(MODEL_STATS_JSON): bench stats scripts/model_stats.py
	$(PYTHON) scripts/model_stats.py \
		--case $(CASE) --kind $(KIND) --scale $(SCALE) \
		--gsim-graph-stats $(GSIM_GRAPH_STATS) \
		--grhsim-graph-stats $(GRHSIM_GRAPH_STATS) \
		--gsim-instruction-stats $(STATS_DIR)/gsim.json \
		--grhsim-instruction-stats $(STATS_DIR)/grhsim.json \
		--bench-log $(BENCH_LOG) \
		--out $@

stat: $(MODEL_STATS_JSON)

one: stat

matrix:
	@mkdir -p $(MATRIX_DIR)
	@for case in $(CASES); do \
		echo "== xs-component $$case =="; \
		$(MAKE) CASE=$$case one || exit $$?; \
	done
	$(PYTHON) scripts/collect_matrix.py --out $(MATRIX_DIR)/results.csv $(foreach c,$(CASES),$(BUILD_DIR)/$(c)/stats/model_stats.json)

clean:
	rm -rf $(BUILD_DIR) out

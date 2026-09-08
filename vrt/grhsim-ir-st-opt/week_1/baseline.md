# Week 1 多仓库共同基线

## 核定结论

本基线于 2026-09-09T00:38:13+08:00 核定，适用于方向 1-3。共同代码起点是根仓库 `3a8558a1618e978c32fc8d3d70c26268879af41d` 及其 5 个 gitlink；递归依赖共 163 项，标准化 `path<TAB>HEAD` 清单 SHA-256 为 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4`。RA/工程师本周不得改写本文件；发现遗漏只能由项目经理派 PI 追加带版本的补充并要求三个方向同口径重验。

项目档案在动作前只有 `project.json`、`requirements.md` 和被忽略的 `.runner/`，没有 `week_*` 目录或历史周报。工程调用计数为 RA 1/2/3 各 `0/6`，本动作未执行或计费工程测试。

## 仓库清单

所有“干净”均由 `git status --porcelain=v2 --branch` 核查；commit/tree 均为完整对象名。

| ID | 实际路径与身份 | 父子关系 / gitlink | 基线 commit | 基线 tree | 核定现场 |
| --- | --- | --- | --- | --- | --- |
| B0 | `/home/gaoruihao/wksp/wolvrix-playground`；`git@github.com:Wolf-Tungsten/wolvrix-playground.git` | 顶层仓库 | `3a8558a1618e978c32fc8d3d70c26268879af41d` | `2d98c233ac99b19b22fb7cd5b2068cb5252f8642` | 分支 `grh/grhsim-ir`；已跟踪内容干净；仅项目档案未跟踪 |
| B1 | `.../reference/gsim`；`https://github.com/OpenXiangShan/gsim.git` | B0 gitlink `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a` | `a3ecb26aa0c18f55c7fbba20e7a9b9d14a25442a` | `306ba84c102e41a03f5d0b0ec5521747ff668861` | 干净；旧分支名 `vrt/grhsim-ir-st-opt/week_1/r_3` 仅为现场，不作基线引用 |
| B2 | `.../testcase/hdlbits`；`https://github.com/Wolf-Tungsten/HDLBits-Verilog-Solutions.git` | B0 gitlink `e9221bbb9289cbed316ddaed0c3d804952c27f48` | `e9221bbb9289cbed316ddaed0c3d804952c27f48` | `5c96e8c27a13f41256a6a08208c9a239bd4ea468` | 干净；旧分支名同 B1；只读测试输入 |
| B3 | `.../testcase/openc910`；`https://github.com/Wolf-Tungsten/openc910.git` | B0 gitlink `e12de7b364c4b5a5dd06317b3a03f6ebc668d89d` | `e12de7b364c4b5a5dd06317b3a03f6ebc668d89d` | `ac522a34953d70315a2652b18384250d34521174` | 干净；旧分支名同 B1；本目标不调用，保留以闭合根基线 |
| B4 | `.../testcase/xiangshan`；`https://github.com/OpenXiangShan/XiangShan.git` | B0 gitlink `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` | `4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6` | `bb4b5dc0ed12891829b69028b09e6352993c6d4d` | 干净；旧分支名同 B1；源码与递归依赖只读 |
| B5 | `.../wolvrix`；`https://github.com/Wolf-Tungsten/wolvrix.git` | B0 gitlink `cba9c32240f3cd06c5b675968b56046e5b76f818` | `cba9c32240f3cd06c5b675968b56046e5b76f818` | `6bcc50560c2fb21f5e000cc521bec5a5e58d8483` | 分支 `grh/grhsim-ir`，与 origin `+0/-0`，干净；本周主要可写仓库 |

## 直接嵌套依赖

下表记录一级依赖的父 gitlink、commit/tree；各 tree 继续以 Git Merkle 关系固定更深 gitlink。全递归清单用前述 163 项哈希复核。

| 父项 / 相对路径 | 仓库身份 | gitlink 与 commit | tree |
| --- | --- | --- | --- |
| B1 / `ready-to-run` | `git@github.com:jaypiper/gsim-ready-to-run.git` | `9f476f8b72eb517cb70c1ad1aa92638c419d3034` | `f6a3f94842b47d93c2a5e4b305f4c2eb383edfa3` |
| B4 / `ChiselAIA` | `https://github.com/OpenXiangShan/ChiselAIA.git` | `53edde5226123e0ce9daa016b9f9b049866d3980` | `98c5f8f27b0186fedb5f96369af25d4fd00b6b67` |
| B4 / `ChiselIOPMP` | `https://github.com/OpenXiangShan/ChiselIOPMP.git` | `435815008053614c2e338439a16b2a1359931c9e` | `e21f0b43bcd130bf5af68cd1ba12005018415114` |
| B4 / `coupledL2` | `https://github.com/OpenXiangShan/CoupledL2.git` | `8795306349398ff7a9a99156d36cf39c1be4dab0` | `41be6e27eb0cbe6fa1602a2ea1d20168cca75582` |
| B4 / `difftest` | `https://github.com/OpenXiangShan/difftest.git` | `5d20df0547758922d9f4fc8aa24b803af4ffbb6a` | `628c830d1eb7b9be40cfca6431f61e1f2592f6da` |
| B4 / `huancun` | `https://github.com/OpenXiangShan/HuanCun.git` | `65ef077373ecf398b4cecdea06b65ef9b8d79044` | `bf7aab8b39194fd99435a75c74f27b895f616063` |
| B4 / `openLLC` | `https://github.com/OpenXiangShan/OpenLLC.git` | `ea9656a4e4cab88216c2ea762534aa29c46c7df4` | `980432b1d8386c79b8837b44c2053e4d20b1e0f4` |
| B4 / `ready-to-run` | `https://github.com/OpenXiangShan/ready-to-run.git` | `912f92121570bd28cabbefa7fa56d25b9784c304` | `f922f0f8e37aef82e65248349daf2a59f35aa54c` |
| B4 / `rocket-chip` | `https://github.com/OpenXiangShan/rocket-chip.git` | `18f902dea0cc94f7a0ec623fce946ec87ded4344` | `07e83f480adc7c976b37a09e5cdb908892a46a78` |
| B4 / `utility` | `https://github.com/OpenXiangShan/Utility.git` | `1db5122533808bcde35c1f4c8bbc62c99777e292` | `52d927b828c9be3043253fe3330ba4f4ac1e5b94` |
| B4 / `yunsuan` | `https://github.com/OpenXiangShan/YunSuan.git` | `447cd17b1637f998daeb6be3efcd4890f48cb2b9` | `bed957686f09c0488a83785b54e05c0963d8a6ae` |
| B5 / `external/libfst` | `https://github.com/gtkwave/libfst.git` | `2188498e74e044f6e4371eee78051389f4bdd304` | `6be9d0b10ceb3b5a93083f7bb4df8dca034fa1b6` |
| B5 / `external/mt-kahypar` | `https://github.com/kahypar/mt-kahypar.git` | `d22e61437568c151d1d2e04d2d7eced052c41042` | `df54f60228aece8a50f6da48d08a6f4053f69fc4` |
| B5 / `external/slang` | `https://github.com/MikePopoloski/slang` | `301723fe5993f8b08ddb933de501b17531d875a5` | `6625689395119f511986d6e8fc82c7abf7f271ad` |

更深依赖复核命令：

```bash
git submodule foreach --recursive --quiet 'printf "%s\t%s\n" "$displaypath" "$(git rev-parse HEAD)"' | sha256sum
git submodule status --recursive | wc -l
```

根现场输出分别为 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4  -`（退出码 0）和 `163`（退出码 0）。三个方向复制后的输出相同，且 `git submodule status --recursive | awk '$1 ~ /^[-+U]/ {print}'` 均为空、退出码 0。

## 源码冻结与允许范围

- 禁止修改 GRH IR 与 GRH pass：B5 的 `include/core/grh.hpp` blob `856ebe2c48eaf12e7bb08e14a7a77884ff815a20`、`lib/core/grh.cpp` `9dd6f1498ac2c05dc4741c729ce7a02ee3578fa0`、`include/core/transform.hpp` `6f4278553999fa4acb950d1094795dd8d6d6d872`、`lib/core/transform.cpp` `7566dd3d81f79a47c1f8de83ec451de4d8fdc71d`、`include/transform` tree `b5c4a1fe42bc68abdc74ee0268f1515ec1917a38`、`lib/transform` tree `b4f0937527c722a1eabb17068491257ca733a49a` 必须保持不变。
- B4 Xiangshan、B2/B3 测试源码及所有递归依赖只读，候选不得更新其 gitlink、tracked/untracked 内容。
- 可改 B5 的 GrhSIM IR 语义、转换后端、CPU mapping/schedule/emitter/runtime 和相邻测试；基线 tree 为 `include/grhsim` `bf3ec81689f558ff30555653326f6a4ccafc35b4`、`lib/grhsim` `e697b581cfc49b946f06add6c825c46fd38db6b4`、`tests/grhsim` `bb68201bf937c9d41d00bc2177613bb51553a760`。根 Makefile/script 只有在承载通用入口时可改，禁止按 Xiangshan 特定模块名匹配。
- 所有算法只能按 IR op、类型、位宽、拓扑、依赖、活动度或通用成本匹配；禁止按模块、实例或层级名称匹配。
- B0 流程源码指纹：`Makefile` blob `85499116eddd1637f0bfcbd850d67cf6ed8813ef`、`scripts/wolvrix_xs_grhsim_ir.py` `e5df20ac7cb02b6964d9f9da6354ac2e1b674c1d`、`scripts/wolvrix_xs_grhsim.py` `eb254fad82bd8ac5fc58d80b3f5319dc701ce7fd`、`env.sh.template` `7a424a1c684b7cbfa8a8c8bc39b64bd1d74200b0`。

## 用户现场处理

- `vrt/workflow/*` 视为用户控制文件并保留。实际 `git diff --quiet HEAD -- vrt/workflow` 退出码 0，即核查时没有已跟踪差异；`vrt-workflow.md`、`race_contract.md`、`pi_plan.tmpl.md` 的 SHA-256 分别为 `9be9bfdaf49f539df879da1374e5b5a23a12aa06ee59af9b07ad5de49fb02d90`、`c19a0bbbe802972e30b743406f823362cd3ed453e58ea9ae1a50d79ff89eb84f`、`d87ffbb84b2c631316083e30ba60c01ce7b12a93685d308885b65f88d0290783`。它们不属于方向候选差异，RA/工程师不得修改。
- `vrt/grhsim-ir-st-opt/project.json` 与 `requirements.md` 动作前未跟踪，SHA-256 分别为 `3db3dfd5bdb41956f270538ba90d982368f0d08a031ccfc6db03b189176696a0`、`00a697b374474783c1d9f404c6f410f017c120eaa4a559eab78072e71c12b8b6`；原文未改，纳入研究档案提交，不纳入技术代码基线。`.runner/` 由 `vrt/.gitignore` 排除，禁止提交或修改。
- 旧 `ptmp/vrt-grhsim-ir-st-opt-c9a4c84b` 根 worktree 为 `413cd043723ea91bd782b0922c1ffcbc949f36af`、`0567b6c7d0261ddd1834daffa8f15327c7f5810a`、`0567b6c7d0261ddd1834daffa8f15327c7f5810a`，不等于 B0；`ptmp/grhsim-ir-st-opt` 只有旧实验目录。B5 worktree 清单还含 `build/tes/grhsim-am-coremark/*` 的 prunable 记录，物理 `build/tes` 不存在（`stat build/tes` 退出码 1），并含用户的 `/tmp/wolvrix-prev`。这些现场均未清理、未复用、未写入。

## 输入与构建复用

| 项目 | 固定值 / 指纹 | 处理 |
| --- | --- | --- |
| workload | `testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`，16712 bytes，SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` | B4 只读 |
| NEMU diff | `testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so`，567504 bytes，SHA-256 `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` | B4 只读 |
| 复用 RTL | `/home/gaoruihao/wksp/wolvrix-playground/build/xs/rtl/rtl`，文件树 SHA-256 `ec1f3ec08a5ea5fc385b0a1782dad6a5445dd56765487c420501549ed06c6ad0` | 三方向只读引用；不得重写 |
| 复用 difftest 生成输入 | `.../testcase/xiangshan/build/generated-src`，文件树 SHA-256 `e0ffc561110cf8c38d6967d55389363601487c039016b9659c0909862dc1db95` | 三方向只读引用；不得重写 |
| 环境入口 | `/home/gaoruihao/wksp/wolvrix-playground/env.sh`，SHA-256 `af581b9382a0050caa3a1d2943966fd6a3bc6f01d59ffd54785ce6a4a9e85ed4` | 共享工具配置，只读；方向 make 传 `ENV_FILE` |
| Python 环境 | `/home/gaoruihao/wksp/wolvrix-playground/.venv`，Python 3.12.3；`pip freeze` SHA-256 `b4226fb757a8ac7b9e3ec0b5ec437ded2c44eb053352c430101b356db3faed51` | 复用；每次目标入口的 `make py_install` 必须重装本方向 B5，日志证明来源 |
| 参考 GSim | `reference/gsim/build/gsim/gsim` SHA-256 `e0c81e2b3fb22c18c0eba2e2aee5a47cf8c9430508a1a45eba5813c1f54c05a3`；需求参考约 40 s | 只作参考，不参与候选正确性替代 |

根 `build/xs/grhsim-ir` 文件树 SHA-256 为 `32b88c4ab199ece3717b9835a1cf0131de4770eb3a94380d5defa1e1cfa520f8`，现有 emu 为 `58710fd69e873b4b6c7d49796a7399d79c29909572b6c9f41e0c9959f6cd8da2`。二者来源不是本周隔离候选，明确排除；不得复制、运行后冒充方向结果。各方向生成模型、对象、emu、日志和缓存全部写入本方向 `ptmp/week_1/` 或 B5 `build/`。

## 环境与复现口径

- 主机：`corvus02`，Ubuntu 24.04.4，kernel `7.0.0-28-generic`，AMD Ryzen 9 7950X3D，16 cores/32 threads，187 GiB RAM；CPU 2 的 SMT sibling 为 CPU 18。
- 工具：Git 2.43.0、GNU Make 4.3、CMake 3.28.3、Clang/Clang++ 22.1.2、Verilator 5.051、ccache 4.9.1、glibc 2.39、numactl 2.0.18；`ninja --version` 退出码 127，未安装。
- 模拟固定 CPU 2，`XS_NUM_CORES=1`、`XS_EMU_THREADS=1`，并以 `taskset -c 2` 把进程及其线程限制在单一逻辑 CPU；waveform/perf/commit trace 关闭。编译可固定并行度 16，这不构成模拟多线程加速。
- 固定运行参数：CoreMark two-iteration image、NEMU difftest、seed 输出必须为 0、`XS_SIM_MAX_CYCLE=50000`、`XS_LOG_BEGIN=0`、`XS_LOG_END=0`、`XS_PROGRESS_EVERY_CYCLES=1000`、`XS_ZERO_INIT=0`。
- 正确性要求：Make 入口退出码 0，达到 50000-cycle limit，无 difftest mismatch/abort/fatal；最终计数及去除仅 `host_ms`/计时字段后的 50 个 progress 记录须与本共同基线首轮实测一致。历史预期锚点为 `Guest cycle spent=50001`、`cycleCnt=49996`、`instrCnt=73580`、终点 `0x80001312`，首轮若不符只记录阻塞，不得自行改口径。
- 完整生成、编译和运行命令及计时方式由 `pi_plan.md` 固定。首轮尚无本 commit 的新鲜编译时间和 50k 单线程时间；这是三方向第 1 次工程调用必须共同补齐的验收缺口，不影响代码/输入基线已经核定。

## 核查命令与退出码

| 命令 | 结果 | 退出码 |
| --- | --- | ---: |
| `find vrt/grhsim-ir-st-opt -maxdepth 4 -mindepth 1 -not -path '*/.runner/*' ...` | 动作前仅 `project.json`、`requirements.md`；无 week 报告 | 0 |
| `git rev-parse HEAD 'HEAD^{tree}'` | B0 commit/tree 如表 | 0 |
| `git ls-tree HEAD reference/gsim testcase/hdlbits testcase/openc910 testcase/xiangshan wolvrix` | 5 个 gitlink 与 B1-B5 完全一致 | 0 |
| `git submodule status --recursive` | 根现场 163 项，无 commit 偏移 | 0 |
| `git submodule foreach --recursive ... | sha256sum` | 清单哈希 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4` | 0 |
| `git diff --quiet HEAD -- vrt/workflow` | 无实际 tracked diff；仍按用户现场保护 | 0 |
| `sha256sum` workload、NEMU、RTL、generated-src | 指纹如表 | 0 |
| `stat build/tes` | 物理目录不存在；仅 B5 Git 元数据留有 prunable 记录 | 1 |

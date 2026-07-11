# NO0330 Direct model-build compiler correction

日期：2026-07-12

## 1. 失败现象

执行 [NO0329](./NO0329_batch_function_page_alignment_plan_20260712.md) 的首次 direct model build 时，
NO0286/NO0300 两边都在 PCH 后的第一批 state object 编译处立即失败：

```text
g++ ... -include-pch grhsim_SimTop.hpp.pch ...
<command-line>: fatal error: -pch: No such file or directory
```

两次失败日志为：

```text
build/logs/xs_perf/no0329/no0286_align4k_model_build.log
build/logs/xs_perf/no0329/no0300_align4k_model_build.log
```

失败时两个副本均未生成任何 `grhsim_SimTop_sched_*.o` 或 `libgrhsim_*.a`，没有进入 batch 编译，
也没有运行仿真。原 NO0286/NO0300 目录未修改。

## 2. 根因

generated Makefile 使用 `CXX ?= clang++`，但 GNU Make 的内建变量已经定义 `CXX=g++`，因此直接执行
子目录 Makefile 时 `?=` 不生效。该 Makefile 使用 Clang 的 `-include-pch` 接口，GCC 将其错误解析为
`-include -pch`。

仓库标准顶层 Makefile 会在 `CXX` 来源为 default/undefined 时显式设为 `clang++` 并 export；difftest 的
`grhsim.mk` 再把该值传给 generated Makefile。原 NO0286 batch object 的 `.comment` 也确认编译器为
Clang 21.1.5。因此这是 direct-build runbook 漏项，不是 generated code 或对齐 flag 失败。

## 3. 修正

重新 `make clean` 两个实验副本，并在 direct model build 显式传入标准工具变量：

```text
CXX=clang++ AR=ar ARFLAGS=rv
```

编译 flag 仍严格为：

```text
-std=c++20 -O3 -falign-functions=4096
```

修正后须重新确认没有残留 GCC object，再从 PCH 开始完整构建。后续独立调用 generated Makefile 时均不得
依赖其 `CXX ?=` 默认值。

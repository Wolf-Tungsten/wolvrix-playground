# TNO0386：从 Makefile 生成器移除默认 no-SLP 规则

日期：2026-10-30。用户决定不再保留自动 `-fno-slp-vectorize`；后续编译器错误在
Clang 层定位修复。用户进一步明确要求修改 Makefile 生成器源头，不使用脚本覆盖补丁。

## 最终修改

修改 [`grhsim_compiler_compat.hpp`](../../wolvrix/lib/emit/grhsim_compiler_compat.hpp)
中的 `emitGrhSimCompilerCompatibilityMakefile()`，删除 LLVM21/SSE2 及 LLVM21/23
bool change-reduction 的编译器/架构判断和自动 no-SLP 选项。现在生成：

```make
# Preserve compiler optimization defaults; no automatic workaround flags.
GRHSIM_COMPILER_FLAGS :=
```

原生单模型与 GrhSIM RepCut 包的 Makefile 都调用这个共用生成函数，因此两者从源头
使用编译器默认优化。没有更改 RTL、生成计算表达式、活动调度或 Verilator 后端。

单线程脚本保持修改前的行为，不添加命令行 `GRHSIM_COMPILER_FLAGS=` 覆盖、不添加
自动 clean、不修改日志解析器。最初尝试的这些附加改动已按用户要求全部撤回；相关
临时测试也未保留。特性说明同步更新，历史基线与历史实验记录继续保留。

既有生成物不会因修改 C++ 生成器源码而自动变化；之后重新生成 Makefile 才获得新规则。
本轮验证使用独立副本重编译，原先冻结的 binary 和 8 次基线记录没有覆盖。

## 验证口径

- 保留现有 compiler-compat 测试及两个 Clang 缩减复现用例，没有删除或放宽失败判定。
- 系统 GCC 13 / Clang 19 编译器探针通过。
- Clang 23.1.2 的既有 change-reduction 复现仍失败：
  `from=0 to=172 changed=1 flags=0`。这项是已知编译器问题，未标为修复或伪报通过；
  使用该探针的旧自动流程仍会报告失败，不自动恢复 no-SLP。
- 以冻结的真实 XiangShan 单模型 C++ 做 Clang23 `-O3 -march=native` 重编译；
  不是本轮重新从 Chisel elaboration，不能将它称为新的完整 clean 生成基线。
- 先前脚本覆盖版本的功能验证已在 CPU96 完成 C100000，NEMU 通过。最终还使用
  共用生成函数实际输出的 Makefile 规则、恢复原样的脚本重新编译，并核对 131 个模型
  对象的真实命令及最终 binary 身份；最终结果追加如下。

验证产物位于 `wolvrix/build/artifacts/grhsim-slp-default_20261030/`。

- [编译器探针结果](../../wolvrix/build/artifacts/grhsim-slp-default_20261030/compiler-probes.json)
- [Makefile 规则生成与完整模型重编译验证](../../wolvrix/build/artifacts/grhsim-slp-default_20261030/validate_generator.py)
- [最终重编译日志](../../wolvrix/build/artifacts/grhsim-slp-default_20261030/source-validation.log)

本轮不发布 walltime 改善或新的正式性能基线。实际代码页局部性与配对测量要求仍见
[TNO0385](./TNO0385_native_single_thread_code_page_locality_control_20261030.md)。

## 完成：源头修改的最终验证

最终使用共用 C++ 生成函数输出 Makefile 规则，再由**未添加覆盖参数的原样单线程脚本**
重编译。131/131 个模型对象的实际命令均为 native O3，未出现 `-fno-slp-vectorize`；
脚本文件与此前冻结的 `reproduce/grhsim_single_baseline.py` 逐字节相同。
生成的最终 binary 与已经完成 CPU96 C100000 功能验证的 binary 逐字节一致：

```text
SHA256 8ca2403cc0eb0ad305a41c30337ce0a647cdb0f4ac4f80f401e9bf4b6771ce65
PC 0x80000c0c
instrCnt 240349
cycleCnt 99996
Guest cycles 100001
```

22 项现有 Python 测试通过。GCC/系统 Clang 19 探针通过，Clang23 独立探针依然失败，
上述功能通过只覆盖本次固定输入前缀，不代表编译器错误已经修复。
两个仓库的 `git diff --check` 通过。

最终生产代码改动只在 Makefile 共用生成器；没有保留脚本覆盖、自动清理或新的测试分支。
新功能验证 binary 保存在独立 artifacts 目录，原先的 no-SLP 历史基线仍保持原样。

- [最终生成器验证结果与实际编译命令](../../wolvrix/build/artifacts/grhsim-slp-default_20261030/source_validation.json)
- [Python 测试日志](../../wolvrix/build/artifacts/grhsim-slp-default_20261030/final-python-tests.log)
- [功能验证日志](../../wolvrix/build/artifacts/grhsim-slp-default_20261030/full_model/runtime.log)

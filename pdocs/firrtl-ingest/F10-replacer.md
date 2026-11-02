# F10 AheadBtbReplacer 独立验证与 reference 断言缩减

实际 frozen `AheadBtbReplacer` 的 native FIRRTL off/prefer、SV ingest 和
Verilator `-O0` 路径均与独立 PLRU scoreboard 一致：241,988 cycles、483,976
个双时钟电平记录，每路检查 1,451,928 个输出位，零排除位、零差异。
默认优化的 Verilator 路径仍会触发原始 `AheadBtbReplacer.sv:124` 断言；
保留这个失败，并已缩减为原始模块的 6 周期输入。

这项组件验证没有修改 DUT、关闭断言、调整全核 reference 或豁免全核失败。
默认优化 reference 不能据此记为通过；全核 CoreMark 的验收仍以完整运行结果为准。

## 输入身份与断言

输入是 F03 frozen 源，未使用另一次 Chisel 生成结果：

| 输入 | SHA256 |
| --- | --- |
| `ptmp/xs/rtl/rtl/SimTop.fir` | `cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a` |
| `AheadBtbReplacer.sv` | `e20c8011f728b8f1a0be5cfdc59fc5a24bfbbcdaa0694307000382e8467c6b02` |
| `PlruStateGen.sv` | `bc63c83efb34b7622391c8a32e41c040ccb2a25854c032af888e6054078e7ca8` |
| `PlruStateGen_1.sv` | `15934d6b108f7a5f65b8945c9cc80a9a54142082a78831bffdc973dfc4916f2d` |
| `ReplacerState.sv` | `9ed51f8308bc13303c1d926e0806a4717f3afd32dc94a3e866e5f363be6ab04f` |

完整身份记录在 `ptmp/firrtl-ingest/F10/replacer/identity.json`。
native 启用 `Verification.Assert/Assume/Cover`，最终图保留
`firrtl.effectKind=assert` 的 `grhsim.system-task fatal`。
SV ingest 保留实际 `xs_assert_v2` 调用，driver 在调用时以非零状态退出。
两个 Verilator 配置均开启 `--assert`，使用实际 `assert.v` 和相同的终止 hook。
没有定义 `SYNTHESIS`、`TB_NO_DPIC`、`STOP_COND=0` 等绕开断言的宏。

## Scoreboard 与覆盖

`scripts/xs_firrtl_replacer.py` 用独立的迭代树遍历表示 32 份 7 位 PLRU 状态。
节点采用 postorder 编号，根是 bit 6，ways 0–3 子树根是 bit 2，ways 4–7
子树根是 bit 5。touch 沿访问 way 的路径把节点指向另一子树；victim 沿节点
选择的子树走到叶子。没有直接复用 Scala 或生成 SV 的递归切片表达式。

输入含义与更新顺序：

- `io_readSetIdx` 选择预测读/写 set；`io_readWayMask[i]` 选择要 touch 的 way。
  `io_readValid=1` 时按 way 0 到 7 依次更新，因此后面的有效 way 决定重叠路径位。
- `io_writeSetIdx` 和 `io_writeWayIdx` 选择训练写入的 set/way，
  `io_writeValid=1` 时执行。与预测写同 set 时训练写优先；不同 set 可同时更新。
- `io_replaceSetIdx` 独立选择当前 victim 输出所在 set。
- 原始异步 reset 把所有 set 清零。所有输出位在 clock=0 和 clock=1 都比较，
  每个电平重复 eval 三次并要求稳定。

定向覆盖包含 32×256 个读 set/mask、32×256×8 个同 set 读写冲突、
32×256×8 个不同 set 并发更新，以及 32×256 个无效读 set/mask。
还覆盖每个 set/way 的单独写入、零 mask、多位 mask、全部 set 扫描和
seed `0xAB7BF10` 的 8,192 次补充访问。scoreboard 实际观察到全部 128 个
状态和全部 8 个 victim，见 `stimulus-identity.json`。

## 默认 Verilator 的 6 周期复现

使用原始模块及原始依赖，不修改 RTL。所有周期 `replaceSetIdx=9`：

| cycle | reset | read | write | set 9 正确状态（边沿后） |
| --- | --- | --- | --- | --- |
| 0–1 | 1 | 无 | 无 | `0x00` |
| 2 | 0 | 无 | set 9, way 6 | `0x10` |
| 3 | 0 | 无 | set 9, way 4 | `0x38` |
| 4 | 0 | set 9, mask `0x04` | set 10, way 0 | `0x7a` |
| 5 | 0 | 无 | set 11, way 1 | `0x7a` |

默认 Verilator 的 duplicate checker 在 cycle 4 后变为 `0x42`，
primary 保持正确的 `0x7a`。cycle 5 上升沿检查到 victim 7 与 victim 4 不同，
调用原始断言 hook，以失败退出。

`state_vec[9]` 对应整个 packed vector 的 bits 69:63，横跨 word 边界。
原始 SV 的 read-way-2 分支保留 `state_vec[9][5:3]`，但当前 Verilator
生成的 `VAheadBtbReplacer___024root__0.cpp` 分支将高 word 更新为：

```cpp
state_vec_dly[2] = 0x21U | (0xffffffc0U & state_vec_dly[2]);
```

该表达式遗漏应保留的 word bits 4:2，即上述例子中的 `0x1c`。
native FIRRTL、SV ingest 和 Verilator `-O0` 对同一源/输入均保留这些位。
`-O0` 完整对照通过，支持默认 Verilator 优化生成代码出错这一定位。
日志中的 Verilator 标识为 5.051。未修改 Verilator 安装或覆盖原有全核
reference 二进制；后续独立整机 `-O0` 构建记录见 F10-components.md。

历史失败 reference 的生成代码也存在完全相同的漏位表达式：
`ptmp/xs/grhsim-ir-widthfix-20261018_135200/ref/verilator-compile/`
`VSimTop___024root__227.cpp:34016`，对应 `abtb.replacers_0` 的
read-way-2 分支；其余三个 replacer 副本也相同。这将当前最小复现与旧
reference 的实际生成代码关联起来，但不冒充旧二进制全部编译输入的身份清单。

完整刺激首次 state 分歧为 cycle 121220 / step 242441：读 set 9、mask 4，
写 set 10、way 0，primary=`0x7a`、checker=`0x42`。
首次原始断言为 cycle 121222 / step 242445，此前 242,445 条 Verilator
输出均匹配 scoreboard。详见 `replacer-monitor.log`、`diagnosis.json`。

## 重现与结果

构建、运行及 Python 验证均通过 Make target，没有重装 Python binding。
以下公共参数固定本次源身份：

```sh
make test_xs_firrtl_replacer WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python \
  XS_FIRRTL_INPUT="$PWD/ptmp/xs/rtl/rtl/SimTop.fir" \
  XS_FIRRTL_COMPARE_SV_DIR="$PWD/ptmp/xs/rtl/rtl"
make test_xs_firrtl_replacer_minimal WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python
make test_xs_firrtl_replacer_noopt WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python
make test_xs_firrtl_replacer_oracle WOLF_ENV_SOURCED=1 PYTHON=.venv/bin/python
```

第一个和第二个命令保留默认优化 Verilator 的断言失败；第三个命令检查
独立 `-O0` 对照，不替换默认 reference；第四个命令通过 4 个 oracle/harness
单测，包含对全部 128 状态×8 ways 的路径检查以及故意损坏输出的检出。

所有生成文件、编译缓存和日志位于 `ptmp/firrtl-ingest/F10/replacer/`。
关键证据为 `comparison-noopt.json`、`diagnosis.json`、
`minimal/diagnosis.json`、`replacer-run.log`、`replacer-minimal.log`、
`replacer-noopt-compare.log` 和 `oracle-final.log`。
三个 Wolvrix 路径、`-O0` Verilator 和 scoreboard 的完整输出 SHA256 均为
`1472d35f540f509e229d4e355766c5019e6b7afbfc4162ea6f932ce99677ddf8`。

## 相同 frozen SV 的完整 reference 前缀

后续在独立 `ptmp/firrtl-ingest/F10/reference-noopt/` 目录构建原始完整
`SimTop`：Verilator `-O0`、language 1800-2005、`--assert`、threads 2，
保留原始 shared harness、DIFFTEST、CoreMark 和 NEMU。构建和固定
100000-cycle 运行均经现有 `xs_ref_emu` / `run_xs_ref_emu` target，退出 0。
最终提交 238535 条指令，达到预期周期上限，无 NEMU 差异或活动 assertion
hook 诊断；没有声明完整两轮 CoreMark 已完成。默认优化 reference 的失败
仍然保留。

ELF SHA256 为
`8fe47962b22c0424765e59e62d62959cc53ba4d1d5f10d5fd6b2bf278fd3ccf6`。
前后核对全部 frozen RTL、宏、harness、CoreMark/NEMU 内容未变化；
根 Makefile 的工作流变更独立记录。原始 harness 对 reset `$fwrite` 的
stderr 缓冲会使部分文本在最终统计后出现，来源及原始 assertion gate、
CPU 绑定修正和完整运行命令见 [F10-components.md](F10-components.md)。
证据为 `reference-input-identity.json`、`reference-output-identity.json`、
`reference-runtime-result.json` 和 `xs_ref_coremark100k_noopt_cpu23.log`。
这些是 F10 功能验证证据，不作为 F11 性能结果。

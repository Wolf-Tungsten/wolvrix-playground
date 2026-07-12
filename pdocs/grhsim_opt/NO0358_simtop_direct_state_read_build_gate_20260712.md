# NO0358 SimTop direct state-read build gate

日期：2026-07-12

## 1. 构建口径

按 [NO0357](./NO0357_simtop_direct_state_read_fresh_emit_gate_20260712.md) 对 fresh generated C++ 使用标准
XiangShan difftest GrhSIM 入口执行 O3 model build 和 emu link：

```text
GRHSIM=1
CXX=clang++
AR=ar
ARFLAGS=rv
CXXFLAGS=-std=c++20 -O3
NUM_CORES=1
WITH_CHISELDB=0
WITH_CONSTANTIN=0
WOLVRIX_GRHSIM_WAVEFORM=0
```

model 输入与输出：

```text
generated C++:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
emu:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim-compile/emu
log:
  build/logs/xs/xs_wolf_grhsim_compile_no0358_direct_state_read_20260712.log
```

构建前 load average 为 `6.85/9.86/9.42`，主机有 256 个逻辑 CPU、约 933 GiB 可用内存，且没有其他 C++
编译任务。所有命令均先执行 `source env.sh`。

## 2. 完整性门禁

构建成功完成以下步骤：

```text
difftest/support CXX       40
generated model compile   153
generated archive           1
final emu link               1
warning/error/killed         0
exit code                    0
```

153 个 generated compile 命令包括 PCH、state、eval、33 个 state-init 和 117 个 sched translation units；
`libgrhsim_SimTop.a` 包含全部预期 objects。最终产物是未 strip 的 x86-64 PIE executable，不存在缺失 object、
未解析符号或并行编译中止。

## 3. 二进制体积

与相同 schedule/configuration、未开启 direct state-read 的 NO0300 O3 emu 对比：

| Metric | NO0300 | Direct | Delta |
| --- | ---: | ---: | ---: |
| archive bytes | 100,425,230 | 99,341,410 | -1,083,820 (-1.079%) |
| emu file bytes | 94,780,472 | 93,707,232 | -1,073,240 (-1.132%) |
| `size` text bytes | 94,603,599 | 93,532,652 | -1,070,947 (-1.132%) |
| `size` data bytes | 9,368 | 9,368 | 0 |
| `size` bss bytes | 14,688 | 14,688 | 0 |

direct emu SHA256：

```text
cad7eca081fb8f9974be8bafdb996991414a65787b4aa16447f32f79acc6ebd4
```

NO0357 的 generated C++ 缩减已经穿过 Clang O3 和静态归档，最终约 1.07 MB 的 text 减少；data/bss 完全不变，
与保持 persistent state/value storage layout 的实现约束一致。体积变化本身不是性能结论，只用于证明 direct path
没有在优化阶段全部退化回原扫描代码。

## 4. 下一步

本篇只验收 build/link，尚未运行模拟。下一步先运行短 cycle smoke gate，检查初始化、NEMU difftest、assertion 和
`input_fullpass_blocked`；通过后再分别执行 10k 和 50k CoreMark 功能门禁。只有三个功能阶段均通过且 guest 终点与
NO0300 一致，才进入 fixed-ASLR baseline/direct/baseline 性能夹测。

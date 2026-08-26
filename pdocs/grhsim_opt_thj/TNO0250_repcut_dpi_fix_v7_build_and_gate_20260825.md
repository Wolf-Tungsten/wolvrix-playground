# TNO0250: RepCut DPI 修复后的 v7 构建与功能门禁

日期：2026-08-25

状态：`IMPLEMENTED; FUNCTIONAL GATES PASS; FORMAL QUIET-CCD MATRIX BLOCKED BY HOST CONTENTION`。

本记录是 [TNO0249](./TNO0249_repcut_dpi_effect_and_atomic_emit_fix_20260825.md) 的增量闭环，不覆盖旧记录。TNO0249 中记录的早期 wheel/source 快照仍保留；本文的 v7 manifest、源码 hash 和运行结果是修复后最终身份。

## 1. 修复后源码身份

最终源码 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `wolvrix/lib/transform/repcut.cpp` | `71e7c879ca4e7538b640b64027849b444296d528853c53cd7729757f152f987d` |
| `wolvrix/lib/emit/system_verilog.cpp` | `bb8475338f21b4f869ab8f4077e69c7e84222e3bc7058022b8c8955e1b175d85` |
| `wolvrix/lib/emit/verilator_repcut_package.cpp` | `968163525bfd2d6738cb0d1e3d4066c4acb246bc6d8c4e121fb24595832e53f4` |

最后一项包含新增的 Normal -> Early 跨 unit 依赖 fail-fast：如果 normal unit 的结果馈入 early unit，emitter 报错并拒绝生成，而不是产生未排序的 phase。对应 fixture 和断言位于 `wolvrix/tests/emit/test_emit_verilator_repcut_package.cpp`。

## 2. v7 生成物和 manifest

使用最终 wheel：

```text
build/repcut_fix_20260825/wheelhouse-v6/
  wolvrix-0.1.0-cp312-cp312-linux_x86_64.whl
sha256=4c4f2d88e56d2eb499981aa746efc602498d11269e8272239e349a2d32fc51ca
```

由冻结的 RepCut JSON 重新发射 v7，命令和耗时见：

```text
build/repcut_fix_20260825/logs/generate-v7/emit-v7.log
build/repcut_fix_20260825/logs/generate-v7/emit-v7.time
```

发射结果为 `rc=0`，wall `1:25.71`，最大 RSS `33,595,188 KB`。关键生成物身份：

| 生成物 | SHA-256 |
| --- | --- |
| `generated-v7/xs_wolf_repcut/SimTop.sv` | `71994d1cd618f087273735c7284860ecd25edae9dca02d842e62d73246c6f364` |
| `generated-v7/package/.../wolvi_repcut_verilator_sim_common.cpp` | `eedcf24c79e7f7dfcbff055bd57a7a97868676667dd0e9d71c8222e13189904f` |
| `generated-v7/package/.../units.mk` | `c73e12f63e40f81aab6b6310dd69d6f9f03714ca5a21aaae65ac4e28450211a3` |

v5/v6/v7 的上述核心生成文件逐字节相同；v7 的变化主要是生成/构建 provenance 和最终 partitioned build 路径，不能把“生成文件相同”误写成所有 native ELF 都在同一时刻重新链接。

正式 runner 使用不可覆盖 manifest：

```text
build/repcut_fix_20260825/build-manifest-v7-final2.json
sha256=e92779e48e76874898c62a3bd841e3e808a585a0653f15f41c6d2bdb1bdf7352
```

manifest 绑定了 source/generated/input/binary hash、32 个 partition 名称、generation/build log hash、Verilator/Clang/CMake/Python/perf 版本以及 v5/v6/v7 source variant。旧 `build-manifest-v7.json`、旧 wheel、旧生成目录和旧 probe 目录均未删除。

## 3. native 与 partitioned 构建

| 后端/线程 | 实际 ELF | 大小 (B) | ELF SHA-256 | provenance |
| --- | --- | ---: | --- | --- |
| native/1 | `xs-build-v5/native-t1/verilator-compile/emu` | 190058376 | `8cb4fe713e2aa7f1a4f5f6e5ca38fb870dd557d2a8b0eb73396d696266e24e73` | preserved v5 |
| native/2 | `xs-build-v5/native-t2/verilator-compile/emu` | 191033824 | `58e96751004a2e1adc5285279bc142229108049da2ba5931df1ebc520721101d` | preserved v5 |
| native/4 | `xs-build-v6/native-t4/verilator-compile/emu` | 190969816 | `2001c884bc65889f072e9868d85cedbcc82bac3c2b985b48825a54365942d7ca` | preserved v6, generated-equivalent |
| native/8 | `xs-build-v6/native-t8/verilator-compile/emu` | 190304360 | `92e15e1b05eb42b01b74cca4576bdcdcfae06e10e53cdb43a888a27be4c3e02b` | preserved v6, generated-equivalent |
| partitioned/1..8 | `xs-build-v7/partitioned-emu/verilator-compile/emu` | 261042608 | `079ffd23d1437f40c5d9f968b4fff275ece07bea595441b8f94ac31583fc90f4` | post-fix v7 |

partitioned 编译日志为 `logs/build-v7/partitioned.log`，`rc=0`、wall `2:23.30`。native t4/t8 的 v6 build log 与 v7 生成文件逐字节身份已纳入 manifest；它们不是在本轮 Normal -> Early 源码变更后再次 relink 的 ELF，这一限制在性能记录中保留。

## 4. C=10000 功能门禁

使用 `run_native_functional_v6.sh` 和 `run_partitioned_functional_v6.sh` 的 v7 输出目录，八个配置均 `rc=0`，无 assertion/bad trap/mismatch/failure/error 命中，且都得到同一冻结端点：

```text
terminal: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x800027c6
Core-0 instrCnt = 458, cycleCnt = 9996
Guest cycle spent: 10001
```

原始日志、`/usr/bin/time` 和 partition timing JSONL：

```text
build/repcut_fix_20260825/logs/functional-v7/
```

partitioned 四档 timing steps 都是 `20102`，C=100 canary 的 steps 都是 `302`。单次 gate 的 wall 仅作功能/规模 sanity check，完整性能汇总见 TNO0251 的证据边界。

## 5. C=30000 参考对

单独的 post-fix baseline t4 pair 也通过：

```text
terminal: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000442
Core-0 instrCnt = 27809, cycleCnt = 29996
Guest cycle spent: 30001
```

文件位于 `build/repcut_fix_20260825/logs/formal-baseline-v7/`。native t4 wall `26.43 s`，partitioned t4 wall `79.54 s`；该 pair 没有 PMU/ContinuousAudit formal admission，因此只是 golden/reference，不计入正式 32 样本矩阵。

## 6. 回归和正式矩阵状态

最终源上 focused targets 全部通过：

```text
emit-sv-storage-ports             PASS
emit-verilator-repcut-package     PASS
transform-repcut                  PASS
```

CTest 新一轮日志：

```text
build/repcut_fix_20260825/logs/tests-final2/ctest.log
build/repcut_fix_20260825/logs/tests-final2/ctest.time
```

结果为 `52/53 PASS`，唯一失败仍是既有 `transform-comb-lane-pack`：

```text
[comb-lane-pack-tests] Expected one packed kAnd for storage frontier rewrite
```

formal runner 已强制要求同 manifest 的 16 槽 canary，且每个 accepted/raw record 记录 manifest/source/generated identity 和启动/结束 ELF hash。实际尝试目录如下，全部没有 accepted sample：

| 目录 | 主要拒绝原因 | raw SHA-256 |
| --- | --- | --- |
| `results/formal_v7_final2` | `runtime_foreign_task_load`, admission idle | `93c63bbf8d555f3b978e9af45d2c63348aa3566b0b2d8237ef2f342ccfef4109` |
| `results/formal_v7_final2_ccd152` | `runtime_guard_mean_idle`, foreign load | `ee000c180dc505e8c18ba05f6e1419860cb55b17ae887b21618dce7f1fac1cb1` |
| `results/formal_v7_final2_ccd176` | `runtime_foreign_task_load` | `6d21068ac4a1228922db7be1073968ef0c648fd97311c39724b199b8b79ceb27` |

例如 ccd176 的首个长样本观测到 `foreign_cpu_ticks=1347`，该运行时长对应门限仅 `37`；任务来自长期 `hapi/GC/HeapHelper`，不是仿真进程。因而没有放宽 quiet/foreign gate，也没有把这些受污染 wall time 写成正式性能结论。共享机器恢复可用的整段 quiet CCD 后，可直接复用同一 manifest、canary 和 runner 重新执行新 output tag。

## 7. 结论

- TNO0241 的 DPI effect/原子提交修复已在最终源上构建，并通过 focused、功能 C=100/C=10000 以及 C=30000 golden reference。
- 新增 Normal -> Early 跨 unit fail-fast，避免后续出现隐式未排序 phase。
- 完整 32 样本 formal 性能矩阵不是“失败的仿真”，而是被共享主机的外部任务门禁阻断；保留 raw 证据，未伪造 headline。
- 旧产物和早期文档继续保留；本文只作为 post-fix v7 的增量记录。

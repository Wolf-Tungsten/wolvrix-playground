# TNO0042：向量译码掩码正式生成与功能门

日期：2026-11-11（America/Los_Angeles）。实现和原型见 [TNO0041](./TNO0041_vector_decode_reduction_masks_20261111.md)，正式计时见 [TNO0043](./TNO0043_vector_decode_masks_walltime_20261111.md)。

## 固定输入与构建

以原 after seed7、Clang 23 构建为 A，用修改后的 `grhsim32_replay` 从其冻结的 `partitioned.json` 生成 B。未运行 Chisel、重新分区或修改 XiangShan/DiffTest。

| 输入 | 身份 |
|---|---|
| XiangShan | `defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0` |
| DiffTest | `b17a43ad24ae2d137f263d667787d3968505b771` |
| Wolvrix 基础提交 | `3a749d2a519d77a9e974c026db41601f36e99560` 加本次补丁 |
| 分区图 SHA256 | `83169bf392ba659b18666c08263595005d2a25686dc54d10774a41240121bbab` |
| assignment SHA256 | `3923e97d5b8c3d3c89829582c7f4bd7460c60bb407e5fc64c5a241643f57e8da` |
| 编译器 | 同一 Clang 23.1.2；`-std=c++20 -O3 -march=native -pthread` |

唯一新增 emitter 配置为 `WOLVRIX_GRHSIM_SCALAR_CONCAT_REDUCTION_MASKS=1`。共比较 9,434 个 `.cpp/.hpp/.h` 文件，只有 46 个 `.cpp` 改变，98 个头文件全部一致。其他 9,388 个文件内容相同。保留原对象顺序、64 B section alignment、全部原 harness 对象和编译参数，只重编译变化的模型源文件。

变化文件包含 119 个共享输入词、49,143 个掩码谓词。相关源码 112,470,708 → 30,329,009 B。进一步删除新增 pack 声明、将每个 mask 谓词还原成原表达式后，这 46 个文件全部与原文件逐字节一致；不存在其他代码变化。审计见 [transformation-audit.json](../../build/xs/repcut-vector-decode-20261111/generated/transformation-audit.json)。

| binary | 字节数 | SHA256 |
|---|---:|---|
| A | 119,370,960 | `bd65a10ecc828cd6b0cf232cb0097cf57b103947248f9c1281e171e3de674281` |
| B | 117,241,040 | `e27e6fd69c65dc0412bb893afab3f6841222533ec64058c3656a5e13479a2aac` |

## 实际表达式的编译后等价检查

从全部变化文件提取原始归约和正式 emitter 输出的掩码谓词，按每个节点的独立布尔输入生成两套 C++ 函数，以相同 Clang 23 `-O3 -march=native` 编译。原函数保留原 OR/NOT 表达式，候选保留实际 pack/mask 表达式；逐个比较输出。

输入包含零、全一、walking one/zero、逐个满足每个 mask 的模式、对 mask 中每一位的翻转、补集，以及固定种子随机值。这些输入不要求是合法向量指令，覆盖范围超过 CoreMark 实际产生的译码输入。

46 个可执行检查、119 个节点、49,143 个谓词全部通过：共 **1,339,357 组输入、664,086,425 次谓词结果比较**。这是定向与随机验证，不是穷举所有 64 位组合或完整 RVV 架构测试。首次辅助提取器遗漏未生成 alias 的直接 Boolean slot，导致一个检查程序无法编译；补齐直接 slot 绑定后全部通过，首次记录保留于 `kernel-check/`，通过记录位于 [kernel-check-r1/report.json](../../build/xs/repcut-vector-decode-20261111/kernel-check-r1/report.json)。正式 emulator 本身编译成功。

另外，新增 focused test、原 scalar concat reduction 回归和完整 `emit-grhsim-cpp` 回归全部通过；新测试已注册为 `emit-grhsim-cpp-scalar-concat-reduction-masks`。验证日志索引见 [checks.json](../../build/artifacts/repcut-vector-decode-20261111/checks.json)。

## 完整 DiffTest 与运行配置门

A/B 分别通过 10,000 周期 smoke、100,000 周期验证和预热，随后 16 次正式样本也通过完整 NEMU DiffTest。共 22 次运行，无功能或 placement/locality 拒绝。完整负载签名：

```text
PC              0x80000c1a
instr_count     250838
cycle_count     99995
guest_cycles    100001
stop_reason     cycle-limit
UART            Running CoreMark for 2 iterations\n
runtime_difftest on
```

使用 performance 配置：node030、CPU96–127、32 个单核 affinity 的线程、NUMA1 严格 bind、ASLR disabled、原 `auto` code-page/preload/pinning。每次运行采用独立 NUMA-local runtime 副本，创建/预触页在正式计时之外。`/proc` affinity/personality/NUMA 与 runtime-config 均检查；不做外部 CPU 空闲准入检查。关闭 trace 和额外 runtime profile，保留双方原有 performance phase timing。

原始命令、maps、NUMA、每线程 affinity、日志、功能结果和各样本 binary/dependency 哈希见 [measure-generated](../../build/xs/repcut-vector-decode-20261111/measure-generated/)。

## 产物

- [构建驱动](../../build/artifacts/repcut-vector-decode-20261111/build.py)、[编译后表达式检查](../../build/artifacts/repcut-vector-decode-20261111/check_kernels.py)
- [输入身份](../../build/xs/repcut-vector-decode-20261111/generated/inputs.json)、[全部源文件比较](../../build/xs/repcut-vector-decode-20261111/generated/source-comparison.json)
- [源码快照/身份](../../build/artifacts/repcut-vector-decode-20261111/source-provenance.json)、[Wolvrix 补丁](../../build/artifacts/repcut-vector-decode-20261111/wolvrix.patch)
- [候选构建](../../build/xs/repcut-vector-decode-20261111/generated/)、[完整机器可读报告](../../build/artifacts/repcut-vector-decode-20261111/report.json)

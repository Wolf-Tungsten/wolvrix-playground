# TNO0232：PGO 工具链审计与普通版交叉核验

日期：2026-08-13

## 1. 结论

本轮 PGO **没有使用 BOLT**。node030 上虽然安装了 `llvm-bolt` 和
`perf2bolt`，但实际 GSIM/GrhSIM 产物都走的是 Clang/LLVM instrumentation
PGO：先用 `-fprofile-generate` 插桩，在同一个 SimTop 50k workload 上训练，
再用 `llvm-profdata merge` 生成 profile，最后用 `-fprofile-use` 重编。

GSIM 的构建命令显式设置了 `PGO_BOLT=0`；日志首行是
`GSIM instrumentation PGO build/train/use`。日志中存在 `.profraw`、
`default.profdata` 和 `llvm-profdata merge`，没有 `perf record`、`perf2bolt`、
`perf.data`、`perf.fdata` 或 BOLT 产物。GrhSIM 的插桩和最终编译日志同样分别
包含 `-fprofile-generate=...` 与 `-fprofile-use=...`。

因此，之前“普通 GSIM 与 PGO 很接近”并不是把两个相同 binary 测了两遍，也
不是 BOLT 结果误标成普通 PGO。更早的 PGO 跨引擎对比使用了不同的 node032
CCD，不能用来估算 PGO 相对普通版的自身收益；本记录补做了同 CCD 的 GSIM
plain/PGO 交叉核验。

## 2. 工具与 make 路径

实际构建机为 node030，先执行了仓库要求的：

```bash
source wolvrix-playground-gsim-calibrate-5/env.sh
```

工具版本为 Ubuntu LLVM `19.1.1`：

| 工具 | 实际状态 |
| --- | --- |
| `clang++` | `/usr/bin/clang++`, Ubuntu clang `19.1.1` |
| `llvm-profdata` | `/usr/bin/llvm-profdata`, LLVM `19.1.1` |
| `llvm-bolt` | `/usr/bin/llvm-bolt`, LLVM `19.1.1`，已安装但本轮未调用 |
| `perf2bolt` | `/usr/bin/perf2bolt`, LLVM `19.1.1`，已安装但本轮未调用 |

仓库的 `gsim.mk` 在 `PGO_BOLT=1` 时才进入 BOLT 分支（需要 `perf record`、
`perf2bolt` 和最终 `llvm-bolt`）；本轮明确选择 `PGO_BOLT=0`，走下面的
instrumentation 分支：

```text
clang++ ... -fprofile-generate=<pgo-dir>
emu -i coremark.bin --max-cycles=50000 --diff nemu.so
llvm-profdata merge <pgo-dir>/*.profraw -o <pgo-dir>/default.profdata
clang++ ... -fprofile-use=<pgo-dir>
```

GSIM 训练目录中的文件为 `default_17584871332815876803_0.profraw`
（`9,350,600` bytes）和 `default.profdata`（`9,392,568` bytes）。GrhSIM
训练目录中的对应文件为 `default_17582245126693075651_0.profraw`
（`14,215,224` bytes）和 `default.profdata`（`14,269,952` bytes）。在
`/tmp/pgo_compare_node030_20260813` 下没有找到 `perf.data`、`perf.fdata`、
`.pre-bolt` 或 `.instrumented` 文件；四个最终 ELF 也没有 `.bolt` section。

## 3. 普通版与 PGO 产物身份

普通版均为 `-O3` 且没有 `-fprofile-*`。产物保留在 node030 的私有目录，
并复制到 node032 运行；大小和 SHA-256 如下：

| 产物 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| GSIM plain `emu.plain` | `78,273,960` | `28a06985e7d9c112eb7bcb150d565f4d75eb7266b906714532c5aee95860d272` |
| GSIM instrumentation-PGO `emu.pgo` | `78,285,320` | `58e86edbe6757a80f52160610094672a30345cc9f82e32de52609b7c6a989fd6` |
| GrhSIM plain `emu.plain` | `83,705,968` | `1e24e65744f3ac1ec6fe8dc7cd613291d3c188da6fa82e8dcc4e5dade8edffc8` |
| GrhSIM instrumentation-PGO `emu.pgo` | `93,478,048` | `4d8ecd94f66a675985ffd4870cca664eea0801564c29e88617da7a198ea30ecd` |

GSIM plain 与 PGO 的 SHA、Build ID 和 `.text` 均不同，说明不是同一文件；但
其最终 ELF 大小只差 `11,360 bytes`（`0.014508%`），这与该 workload 上 PGO
没有改变主要生成代码布局的现象一致。功能签名也分别保持在 GSIM 的
`instrCnt=73584/cycleCnt=49998` 和 guest cycle `50001`。

## 4. 同 CCD GSIM plain/PGO 对照

为排除不同 CPU/NUMA 和页缓存造成的误判，在 node032 使用同一 placement、同一
`coremark.bin`/`nemu.so`、固定 ASLR（`setarch x86_64 -R`）和相同的 SimTop
50k 功能/NUMA/PMU/连续 CCD 门禁：

```text
CCD: node0:8-15,200-207
target CPU: 8, SMT sibling: 200, helper CPU: 96
NUMA node: 0
```

四个有效样本的 `Host time spent` 为：

| 顺序 | GSIM plain (ms) | GSIM PGO (ms) | plain mean (ms) | PGO mean (ms) |
| --- | --- | --- | ---: | ---: |
| ABBA (`plain PGO PGO plain`) | `16,983`, `17,083` | `16,941`, `16,982` | `17,033.00` | `16,961.50` |
| BAAB (`PGO plain plain PGO`) | `17,055`, `17,008` | `17,488`, `17,089` | `17,031.50` | `17,288.50` |
| pooled | `16,983`, `17,083`, `17,055`, `17,008` | `16,941`, `16,982`, `17,488`, `17,089` | `17,032.25` | `17,125.00` |

Pooled PGO 比 plain 慢 `92.75 ms`，即 `+0.544555%`；ABBA 单独看 PGO 快
`0.419773%`，BAAB 单独看 PGO 慢 `1.508969%`。plain 的 ABBA/BAAB order
gap 只有 `0.008807%`，PGO 的 gap 为 `1.909489%`，所以这组数据足以说明
“PGO 没有可观测净收益”，但不能把 `+0.544555%` 当作精确的稳定回退值。

四个样本均通过固定 ASLR、CPU affinity、CPU migration=0、PMU scheduled
percent=100%、目标页 NUMA local ratio=1.0、连续 whole-CCD 监控和功能签名
检查。`instructions:u` 也只呈现很小的编译布局差异（plain 约 `85.841629
G`，PGO 约 `85.816793 G`），没有出现“普通 binary 实际被重复运行”的迹象。

## 5. 普通 GSIM 与普通 GrhSIM 对照

另外在同一 node032 CCD 上完成了两轮 plain `-O3` GSIM/GrhSIM ABBA+BAAB。
两轮都使用 `node0:8-15,200-207`、CPU 8、sibling 200、NUMA 0、固定 ASLR；
外部负载导致的样本均由 runner 丢弃，未混入均值。

第一轮 pooled：GSIM `17,034.25 ms`，GrhSIM `43,421.25 ms`，GrhSIM 慢
`26,387.00 ms/154.905558%`。第二轮 pooled：GSIM `17,479.25 ms`，GrhSIM
`43,693.00 ms`，GrhSIM 慢 `26,213.75 ms/149.970680%`。第一轮的 GSIM
order gap 为 `0.325814%`，小于第二轮的 `1.118469%`，因此将第一轮作为
相对更稳妥的记录值；两轮的跨引擎差距都远大于 order 噪声。由于两轮 GSIM
order gap 仍高于历史 `0.25%` 复测线，精确百分比应视为当前机器窗口的量级
证据，不应解读为亚百分比精密估计。

这解释了“普通 GSIM 与 PGO 差不多”的表象：在真正同 CCD 的 plain/PGO
对照里，PGO 本身只改变了约 `0.5%` 以内的净 walltime，远小于 GSIM 与 GrhSIM
之间约 `150%` 的实现差距。原先直接拿不同 placement 的 PGO 结果比较，不能
用于判断 PGO 自身收益；同 CCD 复核没有发现测错或 binary 混用。

## 6. 保留范围

本次只做工具审计、私有构建和运行对照，没有修改 Wolvrix 默认选项、SimpleTES
bench、runtime gate 或正在运行的 checkpoint。若后续要研究 BOLT，应单独以
`PGO_BOLT=1` 生成 `perf.data/perf.fdata`，并在同一 CCD 协议下与本记录的
instrumentation-PGO 和 plain 三方比较；不能把两种 PGO 结果混称为同一方案。

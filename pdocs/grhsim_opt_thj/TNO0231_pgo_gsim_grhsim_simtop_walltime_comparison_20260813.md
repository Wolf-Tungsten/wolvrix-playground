# TNO0231：GSIM/GrhSIM PGO 二进制与 SimTop 50k walltime 对比

日期：2026-08-13

## 1. 结论

在同一份当前 typed-state RTL、同一份 `coremark.bin`/`nemu.so` 和同一台
node032 上，分别生成了 GSIM 与最新 GrhSIM 的 LLVM instrumentation-PGO
版本。以 `Host time spent` 为 headline walltime，四个有效样本的 pooled
结果为：

| 版本 | 平均 walltime |
| --- | ---: |
| GSIM-PGO | `17,097.50 ms` |
| GrhSIM-PGO | `32,141.25 ms` |

GSIM-PGO 比 GrhSIM-PGO 少 `15,043.75 ms`，GrhSIM-PGO 相对 GSIM-PGO 慢
`87.988010%`；等价地，GSIM-PGO 的 walltime 为 GrhSIM-PGO 的 `0.5319488x`
（GrhSIM-PGO/GSIM-PGO=`1.8798801x`）。本记录只回答 PGO 后两种仿真器的
walltime 对比，不把该结果解释为某一种仿真器自身相对非 PGO 版本的收益：本轮
没有保留/测量 GSIM 的 O3 非 PGO 对照，普通 GrhSIM 二进制只作为构建身份参考。

## 2. 源码、输入与身份

实验基线与正在运行的 SimpleTES fresh bench 一致：

| 项目 | 值 |
| --- | --- |
| parent commit | `be78e837bce9c04973f28b8e6bcc5583447369da` |
| Wolvrix submodule | `79ec2037b00f2d4894d72785277ebe3f5d37782d` |
| FIR (`SimTop.fir`) SHA-256 | `429626c84f87f351f2e451773c43842e83081efee1aa3c772fb93d13b304fd57` |
| RTL (`SimTop.sv`) SHA-256 | `15e4d8dc7ef00e729c6e4aef999bc901bd9381dbeb5432ca6b9e8c42f6ea5559` |
| input image SHA-256 | `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e` |
| `nemu.so` SHA-256 | `094c1c4aacec1bc4afda4fee9a07d92dd9726a23e0fadba163214a299207ff9e` |
| toolchain | clang/LLVM `19.1.1`（node030） |

生成模型由上述 FIR 物化后复制到 node030 的私有目录；构建和 profile 目录均为
`/tmp/pgo_compare_node030_20260813`，没有清理或写入当前 SimpleTES 的活动
目录。最终只把二进制和输入复制到 node032 的
`/tmp/pgo_compare_node032_20260813`。

## 3. PGO 构建

每条构建/运行命令均先执行：

```bash
source wolvrix-playground-gsim-calibrate-5/env.sh
```

### GSIM

GSIM 使用 `gsim-gen-emu` 的 instrumentation-PGO 流程，显式设置
`PGO_WORKLOAD=coremark.bin`、`PGO_MAX_CYCLE=50000`、`PGO_EMU_ARGS=--diff nemu.so`、
`PGO_BOLT=0` 和 `LLVM_PROFDATA=llvm-profdata`。训练通过后由
`llvm-profdata merge` 生成 profile-use 数据，再以 `-fprofile-use` 完成最终
链接。训练功能签名为 `instrCnt=73584`、`cycleCnt=49998`、终止 PC
`0x8000131e`、guest cycle `50001`，训练 walltime 为 `44,844 ms`。

| 产物 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| GSIM-PGO `emu.pgo` | `78,285,320` | `58e86edbe6757a80f52160610094672a30345cc9f82e32de52609b7c6a989fd6` |
| GSIM merged `default.profdata` | `9,392,568` | `8cf792b9d92ef8441f528a94c3e8cc7b9e023f142a9253f979f06611335ee044` |

### GrhSIM

GrhSIM 的 make 目标只透传 profile flags，因此按顺序执行：

1. `GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -fprofile-generate=..."` 的插桩构建；
2. 在 `-i coremark.bin --diff nemu.so -b 0 -e 0 -C 50000` 下训练；
3. `llvm-profdata merge`；
4. 用 `-fprofile-use=...` 清理私有 model objects 后重新构建。

训练功能签名为 `instrCnt=73580`、`cycleCnt=49996`、终止 PC
`0x80001312`、guest cycle `50001`，训练 walltime 为 `62,639 ms`。

| 产物 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| 普通 GrhSIM O3（仅构建参考） | `83,705,968` | `1e24e65744f3ac1ec6fe8dc7cd613291d3c188da6fa82e8dcc4e5dade8edffc8` |
| GrhSIM-PGO `emu.pgo` | `93,478,048` | `4d8ecd94f66a675985ffd4870cca664eea0801564c29e88617da7a198ea30ecd` |
| GrhSIM merged `default.profdata` | `14,269,952` | `c905b2dfe0f3896eda90e27db2332518b254ecfa7f7fd8f70536b2e5e7ae2bbe` |

GrhSIM-PGO 二进制比 GSIM-PGO 大 `15,192,728 bytes`（`19.406867%`）。普通
GrhSIM 本轮没有执行正式 walltime，因此不能从本记录推导 GrhSIM 的 PGO 自身
加速百分比。

## 4. node032 运行协议与门禁

正式运行在 node032；ABBA 与 BAAB 使用同一 placement：

```text
CCD: node1:152-159,344-351
target CPU: 152, SMT sibling: 344, helper CPU: 0
NUMA node: 1
```

每个样本都把 binary、image 和 `nemu.so` 以 `cp --reflink=never` 在目标 NUMA
node first-touch 到新 `/dev/shm` inode，然后执行等价于：

```text
taskset -c 152 numactl --physcpubind=152 --membind=1 \
  perf stat -x, -e cycles:u,instructions:u,... -- \
  setarch x86_64 -R emu -i coremark.bin --diff nemu.so -b 0 -e 0 -C 50000
```

所有有效样本的 process personality 为 `00040000`、CPU migration 为 `0`、PMU
scheduled percent 为 `100%`、目标文件页 NUMA local ratio 为 `1.0`，并通过
连续 whole-CCD 监控。GSIM 与 GrhSIM 使用各自功能签名；两者均要求 guest
cycle `50001`、唯一正的 `Host time spent`，且无 mismatch/assert/fatal/error。

标准 GrhSIM runtime 的固定 coverage 页数门禁（参考 ELF 的 `22,260` 页）会因
GSIM-PGO ELF 只有 `19,084` 个 loadable pages 而拒绝 GSIM，即使它实际运行时
已有 `16,347/16,347` 页在目标 node、local ratio 为 `1.0`。因此本次**临时的
跨引擎比较 runner**只把 `min_binary_coverage` 设为 `1e-6`，取消不适用于
跨引擎二进制规模的绝对驻留页数下限；99.9% local-ratio、ASLR、affinity、
PMU、continuous-CCD 和功能门禁全部保留。SimpleTES 默认 runtime 和仓库源码
没有修改。

## 5. 有效 walltime 样本

字母约定：A=`GSIM-PGO`，B=`GrhSIM-PGO`。每组均为两次同一顺序的 paired
samples；先后顺序只影响冷页/频率噪声，不改变 binary 或输入身份。

| 顺序 | GSIM-PGO samples (ms) | GrhSIM-PGO samples (ms) | GSIM mean (ms) | GrhSIM mean (ms) |
| --- | --- | --- | ---: | ---: |
| ABBA (`A B B A`) | `17,192`, `17,319` | `32,327`, `31,987` | `17,255.50` | `32,157.00` |
| BAAB (`B A A B`) | `16,920`, `16,959` | `32,173`, `32,078` | `16,939.50` | `32,125.50` |
| pooled | `17,192`, `17,319`, `16,920`, `16,959` | `32,327`, `31,987`, `32,173`, `32,078` | `17,097.50` | `32,141.25` |

ABBA 中 GrhSIM 相对 GSIM 慢 `14,901.50 ms/86.357973%`；BAAB 中慢
`15,186.00 ms/89.648455%`。GSIM 两个 order mean 的 gap 为 `1.848223%`，
GrhSIM 为 `0.098005%`；相对差距方向在两种 order 中一致，但 GSIM 的绝对
order gap 超过此前消融实验常用的 `0.25%` 复测线，故 pooled 数值应视为本机
当前窗口的正式对比而非高精度微小差异结论。这里的 `~88%` 差距远大于该
order 噪声，结论不依赖于选择 ABBA 或 BAAB。

## 6. 后续影响

本实验只生成和测量私有 PGO 产物，没有修改 Wolvrix 默认选项，也没有改动
SimpleTES bench、pin 或运行中的 checkpoint。当前 SimpleTES 仍可按其
`be78e837`/`79ec2037` 身份继续研究；node030 的构建产物和 node032 的原始
`emu.log`/`perf.csv`/`audit.txt` 保留在各自 `/tmp/pgo_compare_*` 目录，供复核。

# NO0026 GrhSIM Emit `.o` MTime Compile Tail Snapshot（2026-04-24）

> 归档编号：`NO0026`。目录顺序见 [`README.md`](./README.md)。

这份记录不看 build log，而是只用 `build/xs/grhsim/grhsim_emit` 目录里现存 `.o` 文件的修改时间（`mtime`）来做一次“编译拖尾”快照排序。

先把结论写前面：

- 当前目录下共看到 `1009` 个 `.o`
- 最早落盘的是 `grhsim_SimTop_state_init_8.o`
- 最晚落盘的是 `grhsim_SimTop_state_init_2.o`
- 从第一颗 `.o` 到最后一颗 `.o` 的落盘跨度是 **`2755.332 s`**，约 **`45.92 min`**
- 前 `4` 分钟内已经落盘了 `925 / 1009` 个 `.o`，约 **`91.7%`**
- 真正拖尾的是少量尾部 TU，尤其是：
  - `grhsim_SimTop_state_init_2.o`
  - `grhsim_SimTop_sched_954.o`
  - 一串 `grhsim_SimTop_sched_9xx.o`

## 1. 口径与限制

这份排序使用的是：

```bash
find build/xs/grhsim/grhsim_emit -maxdepth 1 -type f -name '*.o' -printf '%T@ %f\n' | sort -n
```

排序指标定义为：

- 以最早 `.o` 的 `mtime` 作为 `0.000 s`
- 其它 `.o` 用 `mtime - first_mtime` 作为“相对完工偏移”
- 本文里所谓“编译时长排序”，实际更准确地说是“**落盘完工时间排序**”

必须明确：

- 这 **不是** 严格意义上的单 TU CPU compile time
- 它混合了：
  - make 调度排队
  - 并行 worker 是否空闲
  - TU 本身的真实编译时间
  - 尾部串行化或资源争用
- 所以它最适合用来找“**谁在拖尾**”，不适合直接当作精确的单文件编译 benchmark

## 2. 快照数据

### 2.1 整体跨度

当前目录快照结果：

| 指标 | 值 |
| --- | --- |
| `.o` 总数 | `1009` |
| 最早 `.o` | `grhsim_SimTop_state_init_8.o` |
| 最早时间 | `2026-04-24 02:14:26.2414191300` |
| 最晚 `.o` | `grhsim_SimTop_state_init_2.o` |
| 最晚时间 | `2026-04-24 03:00:21.5731939940` |
| 首尾跨度 | `2755.332 s` |

### 2.2 最早完成的一批

| 文件 | 相对首个 `.o` 偏移 |
| --- | ---: |
| `grhsim_SimTop_state_init_8.o` | `0.000 s` |
| `grhsim_SimTop_sched_3.o` | `1.688 s` |
| `grhsim_SimTop_sched_2.o` | `1.720 s` |
| `grhsim_SimTop_sched_0.o` | `1.864 s` |
| `grhsim_SimTop_sched_5.o` | `1.864 s` |
| `grhsim_SimTop_sched_4.o` | `1.940 s` |
| `grhsim_SimTop_sched_1.o` | `1.996 s` |
| `grhsim_SimTop_state_init_40.o` | `2.052 s` |
| `grhsim_SimTop_state_init_11.o` | `2.172 s` |
| `grhsim_SimTop_eval.o` | `2.220 s` |

### 2.3 最晚完成的一批

下面这些是当前目录里最明显的拖尾 TU：

| 文件 | 相对首个 `.o` 偏移 |
| --- | ---: |
| `grhsim_SimTop_sched_939.o` | `1933.709 s` |
| `grhsim_SimTop_sched_904.o` | `1966.481 s` |
| `grhsim_SimTop_sched_949.o` | `1976.529 s` |
| `grhsim_SimTop_sched_961.o` | `1983.045 s` |
| `grhsim_SimTop_sched_897.o` | `1999.573 s` |
| `grhsim_SimTop_sched_944.o` | `2005.809 s` |
| `grhsim_SimTop_sched_922.o` | `2029.381 s` |
| `grhsim_SimTop_sched_908.o` | `2035.157 s` |
| `grhsim_SimTop_sched_918.o` | `2047.205 s` |
| `grhsim_SimTop_sched_915.o` | `2107.129 s` |
| `grhsim_SimTop_sched_935.o` | `2112.485 s` |
| `grhsim_SimTop_sched_953.o` | `2116.029 s` |
| `grhsim_SimTop_sched_937.o` | `2193.805 s` |
| `grhsim_SimTop_sched_954.o` | `2391.025 s` |
| `grhsim_SimTop_state_init_2.o` | `2755.332 s` |

如果只看最后 `10` 个文件，对应的绝对落盘时间是：

| 时间 | 文件 |
| --- | --- |
| `2026-04-24 02:47:52.0506987850` | `grhsim_SimTop_sched_944.o` |
| `2026-04-24 02:48:15.6227029930` | `grhsim_SimTop_sched_922.o` |
| `2026-04-24 02:48:21.3987040250` | `grhsim_SimTop_sched_908.o` |
| `2026-04-24 02:48:33.4467061750` | `grhsim_SimTop_sched_918.o` |
| `2026-04-24 02:49:33.3707168740` | `grhsim_SimTop_sched_915.o` |
| `2026-04-24 02:49:38.7267178310` | `grhsim_SimTop_sched_935.o` |
| `2026-04-24 02:49:42.2707184640` | `grhsim_SimTop_sched_953.o` |
| `2026-04-24 02:51:00.0467323500` | `grhsim_SimTop_sched_937.o` |
| `2026-04-24 02:54:17.2667675620` | `grhsim_SimTop_sched_954.o` |
| `2026-04-24 03:00:21.5731939940` | `grhsim_SimTop_state_init_2.o` |

## 3. 分钟桶分布

按“相对最早 `.o` 完工时间”的分钟桶统计：

| 分钟桶 | 完工数量 |
| --- | ---: |
| `00` | `189` |
| `01` | `312` |
| `02` | `276` |
| `03` | `148` |
| `04` | `16` |
| `05` | `4` |
| `06` | `3` |
| `07` | `2` |
| `08` | `3` |
| `09` | `1` |
| `10` | `1` |
| `11` | `0` |
| `12` | `1` |
| `13` | `1` |
| `14` | `2` |
| `15` | `1` |
| `16` | `2` |
| `17` | `0` |
| `18` | `4` |
| `19` | `1` |
| `20` | `0` |
| `21` | `0` |
| `22` | `0` |
| `23` | `0` |
| `24` | `0` |
| `25` | `0` |
| `26` | `0` |
| `27` | `0` |
| `28` | `4` |
| `29` | `3` |
| `30` | `2` |
| `31` | `1` |
| `32` | `1` |
| `33` | `5` |
| `34` | `3` |
| `35` | `3` |
| `36` | `0` |
| `37` | `1` |
| `38` | `0` |
| `39` | `0` |
| `40` | `1` |
| `41` | `0` |
| `42` | `0` |
| `43` | `0` |
| `44` | `0` |
| `45` | `0` |
| `46` | `1` |

从累计值看：

- 前 `4` 分钟（`00` 到 `03`）已经完成 `925 / 1009`，约 `91.7%`
- 前 `5` 分钟（加上 `04`）已经完成 `941 / 1009`，约 `93.3%`
- 前 `31` 分钟已经完成 `993 / 1009`，只剩 `16` 个 `.o`

这说明当前 build 的主要问题不是“整体普遍都慢”，而是“**少量尾部 TU 把总墙钟时间拖长**”。

## 4. 观察

### 4.1 拖尾高度集中在 `sched_9xx`

尾部大部分都是：

- `grhsim_SimTop_sched_9xx.o`

这和前面直接查看 `grhsim_SimTop_sched_537.cpp` 时观察到的现象是一致的：大 batch / 大表达式密度的 `sched_*.cpp` 是编译拖尾的主要来源。

### 4.2 `state_init_2.o` 是最强离群点

最后一颗 `.o` 不是 `sched_*.o`，而是：

- `grhsim_SimTop_state_init_2.o`

它比倒数第二个：

- `grhsim_SimTop_sched_954.o`

还晚了约：

```text
2755.332 - 2391.025 = 364.307 s
```

也就是最后还额外拖了约 `6.07 min`。这意味着 `state_init_2.cpp` 本身值得单独拆看，不应只盯 `sched_*.cpp`。

### 4.3 当前最该优先优化的是“尾部大 TU”，不是继续抠前段

从这个快照看，优化优先级应该是：

1. 先把尾部 `sched_9xx` 这批大 TU 再切碎或减表达式体积
2. 单独检查 `state_init_2.cpp` 为什么成了最终拖尾点
3. 再考虑是否需要更激进的分桶、拆文件或禁用某些生成模式

## 5. 后续动作建议

- 对 `grhsim_SimTop_sched_904.cpp`、`915.cpp`、`918.cpp`、`922.cpp`、`935.cpp`、`937.cpp`、`939.cpp`、`944.cpp`、`949.cpp`、`953.cpp`、`954.cpp`、`961.cpp` 做单独体积画像：
  - 行数
  - token 数
  - `std::array` 临时值数量
  - 大 lambda 数量
- 单独查看 `grhsim_SimTop_state_init_2.cpp`：
  - 行数
  - 大数组初始化密度
  - 是否存在极长的初始化表达式链
- 下一轮如果要做更精确的 compile profiling，不该只看 `mtime`，而应该在 Makefile 里给每个 TU 打开始/结束时间戳

## 6. 复现命令

本文涉及的统计命令：

```bash
find build/xs/grhsim/grhsim_emit -maxdepth 1 -type f -name '*.o' -printf '%T@ %f\n' | sort -n
```

```bash
find build/xs/grhsim/grhsim_emit -maxdepth 1 -type f -name '*.o' -printf '%T@\n' | sort -n \
  | awk 'NR==1{base=int($1/60)*60} {bucket=int(($1-base)/60); cnt[bucket]++} END{for (i=0;i<=bucket;i++) print i, cnt[i]+0}'
```

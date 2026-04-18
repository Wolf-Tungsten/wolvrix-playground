# GSim / GrhSIM Supernode Edge-Step Tracking Snapshot（2026-04-18）

这份文档单独记录当前 `gsim` / `grhsim` 的静态 supernode 边数与 step/eval 执行统计，并绑定当前 commit，便于后续优化过程做同口径跟踪。

## Commit 锚点

| 仓库 | 路径 | commit |
| --- | --- | --- |
| `wolvrix-playground` | `/home/gaoruihao/wksp/wolvrix-playground` | `bdaf2372f479c1d19a85f04da7265bf80cda7e6a` |
| `wolvrix` | `/home/gaoruihao/wksp/wolvrix-playground/wolvrix` | `648315cff9bc8a15f993e0b127b5eadbbd5ef43f` |
| `gsim` | `/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim` | `e9d9386798373b2293b19294da7e8a912c02e352` |

## 测试口径

- workload：`/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`
- target：`default-xiangshan`
- `gsim` CPU 绑定：`taskset 0x1`
- `grhsim` CPU 绑定：`taskset 0x1`
- `grhsim` 运行窗口：`-C 30000`
- `grhsim` activity profile：`GRHSIM_ACTIVITY_PROFILE=1`

## 统计语义

### 1. 静态边数

- `gsim next`
  - emitted supernode 粒度的 `next` 边
  - 如果 `supernode A` 的多个值都流向同一个 `supernode B`，只记一条 `A -> B`
- `grhsim dag_edges`
  - final activity-schedule supernode DAG 边
  - 同样是 supernode 粒度去重后的 `A -> B`

### 2. 动态 step/eval 统计

- `gsim active_supernodes_per_step`
  - 每进入一个被执行的 supernode 就加一
  - 是 `gsim step()` 内的累计执行次数
- `grhsim executed_supernodes_per_eval`
  - 每个 `eval()` 中，每轮 fixed-point round 扫 active bitset
  - 每次真正执行到 active supernode 都计数
  - 如果跨过 `commit_state_updates()` 再次被激活并再次执行，要再算一次

因此：

- `grhsim` 这里不做去重
- 它和 `gsim active_supernodes_per_step` 在“累计执行次数”语义上是可对齐的
- 但两边时间基准不同：`grhsim` 是 host `eval()`，`gsim` 是它自己的 `step()`

## 静态结构对比

| 指标 | `grhsim` | `gsim` |
| --- | ---: | ---: |
| supernodes | `74906` | `131580` |
| supernode edges | `1225442` | `612269` |
| average outgoing edges / supernode | `16.35973086268123` | `4.653207174342605` |

派生关系：

- `grhsim dag_edges / gsim next = 2.0016x`
- `grhsim avg out-degree / gsim avg next out-degree = 3.5168x`

## 动态执行统计对比

| 指标 | `grhsim executed_supernodes_per_eval` | `gsim active_supernodes_per_step` |
| --- | ---: | ---: |
| samples | `60102` | `1900000` |
| avg | `6169.76` | `10260.63` |
| min | `187` | `2138` |
| p50 | `262` | `10009` |
| p90 | `18873` | `16437` |
| p99 | `26102` | `18487` |
| max | `75680` | `131580` |

按当前口径，可直接记住两点：

- `grhsim` 单次 `eval()` 的累计执行 supernode 数，平均值低于 `gsim`
- `grhsim` 仍然显著更慢，因此问题更可能在 host 侧单次 supernode 成本、fixed-point / commit 框架开销，而不是“每次 step/eval 扫过的 supernode 总数更多”

## 辅助动态量

`grhsim` 当前同批次还拿到了一个额外指标：

| 指标 | `grhsim peak_active_supernodes_per_eval` |
| --- | ---: |
| avg | `457.06` |
| min | `187` |
| p50 | `187` |
| p90 | `991` |
| p99 | `1379` |
| max | `74906` |

这个量表示：

- 单个 `eval()` 内，任意时刻 active set 的峰值宽度

它不是本轮 tracking 的主对齐指标，但有助于判断 `grhsim` 的活跃前沿是否过宽。

## 数据来源

- `gsim` 结构统计：
  - `/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim_default_xiangshan_instrument_20260418/default-xiangshan/model/gsim_instrumentation_summary.txt`
- `gsim` 机制文档：
  - `/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/gsim_default_xiangshan_activation_instrument_20260418.md`
- `grhsim` 结构统计：
  - `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_activity_20260418/grhsim_emit/activity_schedule_supernode_stats.json`
- `grhsim` 运行日志：
  - `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_default_xiangshan_activity_20260418/logs/coremark_nutshell_30k_activity_rerun.log`
- `grhsim` 机制文档：
  - `/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/grhsim_default_xiangshan_activation_instrument_20260418.md`

## 后续建议

后续每次 `grhsim` 优化后，至少按同样格式追加或新建一份 snapshot，固定记录：

1. commit 编号
2. `supernodes`
3. `dag_edges`
4. `average outgoing edges / supernode`
5. `executed_supernodes_per_eval` 的 `avg/p50/p90/p99`
6. `peak_active_supernodes_per_eval` 的 `avg/p50/p90/p99`

这样可以把“静态图变了多少”和“动态执行行为变了多少”拆开跟踪。

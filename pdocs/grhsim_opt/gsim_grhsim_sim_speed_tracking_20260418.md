# GSim / GrhSIM Simulation Speed Tracking Snapshot（2026-04-18）

这份文档单独记录当前 `gsim` / `grhsim` commit 下的仿真速度，作为后续优化过程的速度基线。

## Commit 锚点

| 仓库 | 路径 | commit |
| --- | --- | --- |
| `wolvrix-playground` | `/home/gaoruihao/wksp/wolvrix-playground` | `bdaf2372f479c1d19a85f04da7265bf80cda7e6a` |
| `wolvrix` | `/home/gaoruihao/wksp/wolvrix-playground/wolvrix` | `648315cff9bc8a15f993e0b127b5eadbbd5ef43f` |
| `gsim` | `/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim` | `e9d9386798373b2293b19294da7e8a912c02e352` |

## 测试口径

- target：`default-xiangshan`
- workload：`/home/gaoruihao/wksp/wolvrix-playground/tmp/gsim/ready-to-run/bin/coremark-NutShell.bin`
- CPU 绑定：`taskset 0x1`
- host 环境：同一台机器、同一系统、同一编译器

## 速度统计

| 指标 | `gsim` | `grhsim` |
| --- | ---: | ---: |
| 运行窗口 | full-run `1900000` cycles | sample-run `30000` cycles |
| host wall time | `8:14.30` | `7:40.82` |
| simulated cycles | `1900000` | `30001` |
| host simulation speed | `3843.82 cycles/s` | `65.11 cycles/s` |
| peak RSS | `554 MiB` | `251 MiB` |

补充一个 `perf stat` 口径下的速度：

| 指标 | `gsim` | `grhsim` |
| --- | ---: | ---: |
| `perf` simulated cycles | `1900000` | `30001` |
| `perf` host wall time | `502.50 s` | `444.60 s` |
| `perf` simulation speed | `3781.09 cycles/s` | `67.48 cycles/s` |

## 速度对比

按当前实测：

- `grhsim / gsim` host simulation speed = `0.0169x`
- 也就是当前 `grhsim` 约慢 `59.0x`

需要注意：

- `gsim` 速度来自完整 `1900000` cycle full-run
- `grhsim` 速度来自 `30000` cycle sample-run
- 因为当前 `grhsim` full-run 预计约 `8.1` 小时，不适合做同成本全程基线

因此这份 snapshot 适合用来追踪：

- `grhsim` 优化前后自己的速度变化
- `grhsim` 相对 `gsim` 的量级差距是否持续收敛

但不适合把两边 wall time 机械地看成完全同口径。

## 数据来源

- `gsim` 基线文档：
  - `/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/gsim_default_xiangshan_coremark_baseline_20260418.md`
- `grhsim` 基线文档：
  - `/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/grhsim_default_xiangshan_coremark_baseline_20260418.md`
- `gsim/grhsim` perf 对齐文档：
  - `/home/gaoruihao/wksp/wolvrix-playground/pdocs/grhsim_opt/gsim_grhsim_coremark_perf_alignment_20260418.md`

## 后续建议

后续每次 `grhsim` 优化后，至少补这 5 个量：

1. commit 编号
2. simulated cycles
3. host wall time
4. host simulation speed
5. `perf` simulation speed

这样可以把“体感更快了”变成可持续跟踪的速度曲线。

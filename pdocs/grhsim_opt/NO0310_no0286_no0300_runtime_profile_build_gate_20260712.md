# NO0310 NO0286 / NO0300 runtime-profile build gate

日期：2026-07-12

## 1. 目的

按 [NO0309](./NO0309_no0286_no0300_dynamic_work_plan_20260712.md) 的固定口径，分别重建 strict
NO0286 与 ordered NO0300 的 profile-enabled SimTop C++ 和 O3 emu。本阶段只验收结构、profile 接线和
可执行文件，不包含 50k 动态计数结论。

所有生成和编译命令均先执行 `source env.sh`。两版均从以下 checkpoint 恢复，并显式使用
`final_topo_policy=level-id`：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

## 2. 配置回显

strict NO0286：

```text
reg_to_mem_ordered_writes=False
reg_to_mem_decoded_write_storage=False
final_topo_policy=level-id
```

ordered NO0300：

```text
reg_to_mem_ordered_writes=True
reg_to_mem_decoded_write_storage=True
final_topo_policy=level-id
```

两版 emitter 均设置 `GRHSIM_EMIT_RUNTIME_PROFILE=1`，生成头文件均确认：

```cpp
static constexpr bool kRuntimeProfileCompiled = true;
```

## 3. Fresh 结构门禁

| Metric | strict NO0286 | ordered NO0300 |
| --- | ---: | ---: |
| graph ops | 7,196,059 | 7,204,108 |
| eligible ops | 6,982,222 | 6,990,363 |
| source clones | 2,044,602 | 2,045,861 |
| compute supernodes | 67,449 | 63,241 |
| commit supernodes | 485 | 485 |
| DAG edges | 638,649 | 528,622 |
| boundary values | 1,162,161 | 1,000,463 |
| boundary activation edges | 2,261,833 | 1,983,923 |
| compute-compute value pairs | 2,003,556 | 1,721,698 |
| compute-commit value pairs | 258,277 | 262,225 |
| commit ops max | 42,937 | 42,937 |

两列分别精确复现 NO0286 与 NO0300 的既有结构，profile emission 没有改变 graph 或 schedule。

## 4. Profile 与编译产物

| Metric | strict NO0286 | ordered NO0300 |
| --- | ---: | ---: |
| static TSV data rows | 67,934 | 63,726 |
| generated `.cpp` files | 152 | 152 |
| generated `.cpp` bytes | 1,498,129,678 | 1,386,810,847 |
| emu bytes | 105,699,496 | 96,669,776 |
| emu `.text` bytes | 105,520,414 | 96,489,788 |

两版均用 `clang++ -std=c++20 -O3` 编译，模型并行度限制为 32。最终 emu 中均可检出
`EMU_RUNTIME_PROFILE` 和 `GRHSIM_RUNTIME_PROFILE` 导出字符串。ordered profile binary 的 `.text`
比 strict 小约 `8.56%`，但 profile 自增代码数量随 supernode 数变化，因此该值只作为产物快照，不用于替代
无插桩 runtime gate。

SHA256：

```text
strict  5221b7180de1bd1cfc39d2aa9552b330a5365e09b22c014223f861e2d356310a
ordered c8ce8835fdd8376f820e118803f14851d3420106ebcd9dc74b88aba7f3d08b86
```

## 5. 产物

```text
build/xs_grhsim_no0309_no0286_rtprof_20260712/grhsim
build/xs_grhsim_no0309_no0300_rtprof_20260712/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0309_no0286_rtprof_emit_20260712.log
build/logs/xs/xs_wolf_grhsim_compile_no0309_no0286_rtprof_20260712.log
build/logs/xs/xs_wolf_grhsim_build_no0309_no0300_rtprof_emit_20260712.log
build/logs/xs/xs_wolf_grhsim_compile_no0309_no0300_rtprof_20260712.log
```

## 6. 结论

两套 profile-enabled emu 的配置、结构、static TSV 和最终链接均通过门禁，可以进入同 workload CoreMark
50k dynamic fire/work 对比。下一阶段运行前重新检查主机负载，并核对两版 guest 终点完全一致。


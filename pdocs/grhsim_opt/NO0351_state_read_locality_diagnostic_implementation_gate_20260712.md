# NO0351 State-read locality diagnostic implementation gate

日期：2026-07-12

## 1. 实现

按 [NO0350](./NO0350_state_read_boundary_locality_diagnostic_plan_20260712.md)，在 `grhsim-cpp` emitter 增加
默认关闭的只读诊断：

```text
emit attribute: state_read_locality_stats=1
environment:    WOLVRIX_GRHSIM_STATE_READ_LOCALITY_STATS=1
output:         <emit-dir>/grhsim_state_read_locality.tsv
```

开启后，emitter 在 batch packing 和最终 materialized-value storage layout 建立完成后遍历 schedule 中的
register/latch read ports。每行输出 24 个字段，包括：

- op/value ID、read kind、state prefix/symbol、width/scalar；
- source supernode/batch、supernode 总 op/read op 数和 pure-state-read 标记；
- materialized、same-state alias、canonical value、tracked-change 与 boundary fanout；
- graph user edges 在同 supernode、同 batch其他 supernode、跨 batch 和 unscheduled 中的分布；
- unique user supernode/batch 数。

字段中的 tab/newline/carriage return 会替换为空格，保证 TSV row width 稳定。诊断只构建 op→supernode 与
supernode→batch 辅助映射，不修改 model、schedule、storage layout 或生成代码。默认关闭时不执行遍历和文件写入。

子仓库提交：

```text
0ec1fee feat: emit GrhSIM state-read locality stats
```

## 2. Synthetic gate

在 repeated-state-read generated-model case 中通过 emit attribute 开启诊断，并对 TSV 做结构化解析。结果：

```text
rows                  = 17
materialized rows     = 16
same-state alias rows = 11
pure-state-read rows  = 12
```

测试同时确认 `state_symbol=repeated_q`、materialized/alias 标记和 pure/mixed 分类字段存在，并继续编译、执行原
generated-model harness。其他 cases 不开启开关，artifact tree 中只有该目标 case 生成 locality TSV。

## 3. Build / test

所有命令均先执行 `source env.sh`：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j32
ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
```

结果：

```text
emit-grhsim-cpp PASS 150.92 s
1/1 tests passed
```

## 4. 下一步

从 NO0300 的同一 pre-reg-to-mem checkpoint fresh emit，保持 ordered affine、`level-id`、supernode/batch 参数不变，
只开启 locality TSV。结构计数必须精确复现 NO0300；随后与 NO0311 的 NO0300 50k fire TSV 按 supernode ID
连接，形成独立 SimTop 诊断文档。该阶段不编译 emu，也不修改 runtime 行为。

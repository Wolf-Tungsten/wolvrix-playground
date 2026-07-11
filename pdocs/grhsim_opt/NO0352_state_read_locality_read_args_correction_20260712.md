# NO0352 State-read locality read-args correction

日期：2026-07-12

## 1. 失败

按 [NO0350](./NO0350_state_read_boundary_locality_diagnostic_plan_20260712.md) 首次启动 fresh locality emit 时，将
第五个位置参数写成新 output directory 下尚不存在的：

```text
build/xs_grhsim_no0352_state_read_locality_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
```

脚本在读取 graph/checkpoint 前立即失败：

```text
[wolvrix-xs-grhsim] FAIL: read args file not found
RuntimeError: read args file not found
```

该失败没有执行 reg-to-mem、activity-schedule 或 C++ emission，也没有产生可用于分析的数据。历史 NO0300 命令
指向目标目录中的 read-args，是因为上游构建阶段已经预先生成该文件；从 checkpoint 直接恢复的新目录不具备此前提。

## 2. 修正

后续命令显式复用 NO0300 已验证的 read-args：

```text
build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
SHA256 bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c
```

pre-reg-to-mem checkpoint 旁的旧文件 SHA256 为 `4c406769...`，其 RTL include root 指向
`build/xs_grhsim_event_order_src_20260710/rtl/rtl`；NO0300 文件指向当前标准 `build/xs/rtl/rtl`。为严格复现
NO0300，选择前者而不是旧 checkpoint 旁文件。

其余 graph checkpoint、ordered/decoded、`level-id`、supernode/batch 和 locality 参数不变。重跑结果单独形成
后续文档，本篇不承载结构或分析结论。

## 3. 无效日志

```text
build/logs/xs/xs_wolf_grhsim_build_no0352_state_read_locality_emit_20260712.log
```

重跑使用新的日志名，避免覆盖失败证据。

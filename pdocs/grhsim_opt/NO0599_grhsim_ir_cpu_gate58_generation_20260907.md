# NO0599 GrhSIM IR CPU Gate58 Generation

- 日期：2026-09-07
- 前置：[NO0598](./NO0598_grhsim_ir_cpu_private_scalar_commit_implementation_20260907.md)

## Generation

独立 gate58 从相同 flat GRH 生成，完成 mapping、C++ 发射、JSON 存储、fresh-session
加载及稳定 round-trip，退出 0，88785 ms。

```sh
make --no-print-directory xs_wolf_grhsim_ir WOLF_ENV_SOURCED=1 \
  PYTHON="$PWD/.venv/bin/python" XS_WOLF_DEPS= XS_GRHSIM_IR_BUILD=ptmp/xs_gate58 \
  XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON=build/xs/grhsim/wolvrix_xs_pre_reg_to_mem.json \
  XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON=1 \
  XS_WOLF_GRHSIM_IR_JSON=ptmp/xs_ir_gate58.json \
  XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON=ptmp/xs_ir_gate58_roundtrip.json \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate58 \
  XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT=0 XS_LOG_DIR="$PWD/ptmp" \
  RUN_ID=20260907_gate58_generation TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_gate58_generation.log 2>&1
```

先前 `make py_install` 的默认系统 Python 无 pip，未进入安装；随后明确指定项目
`.venv/bin/python` 的同一 target 已退出 0，日志
`ptmp/grhsim_private_commit_venv_install.log`。PIP_CACHE_DIR/TMPDIR/CCACHE_DIR
均指向 ptmp。生成命令清空已满足的 XS_WOLF_DEPS，避免重复安装，不绕过生成路径。

## Identity and Coverage

`cmp -s ptmp/xs_ir_gate57.json ptmp/xs_ir_gate58.json` 退出 0，完整 IR 和 CPU mapping
逐字节相同。新旧公开头文件的私有实现布局不同，所以使用独立 harness 构建目录。

实际生成 task 标记统计：

| Metric | Value |
| --- | ---: |
| Direct scalar commit states | 284775 |
| Batched history states | 391659 |
| History batches | 3240 |
| Largest history batch | 8030 bytes |

history 覆盖与 gate57 相同。task_5570 源码从 2198057 增至 2717943 字节；新增
显式比较等语句使源码变长，不能据源码形态宣称二进制缩小或运行加速。

## Running Gates

原 Makefile 的 O3 全模型构建已启动，VM_BUILD_JOBS=8，模型目录
`ptmp/xs_emit_make_gate58`，harness 根目录 `ptmp/xs_gate58`。日志
`ptmp/grhsim_gate58_full_o3_build.log`。不同 ABI 不与 gate57 混链，gate57 的默认
入口仍保留为已验证 50k 的基线。

HDLBits 全量也在运行，日志 `ptmp/grhsim_ir_hdlbits_private_commit.log`，产物目录
`ptmp/hdlbits-grhsim-ir-tEJANI`。两项结束后才进行性能运行，不把编译负载混入计时。
gate58 的真实运行正确性与性能尚未验证，目标保持未完成。

## Incremental Coverage Detail 2026-09-07

生成 task 内有 216523 个 `cpu_direct_state_changed` 调用站点，对应 E 内的 direct
状态；其余 68252 个 direct 状态在 E 外，不调用延续/激活 helper。两者合计 284775。
这是静态站点统计，不是运行期变化次数或时间占比。

# NO0591 GrhSIM IR CPU Gate57 Full O3 Build

- 日期：2026-09-07
- 前置：[NO0589](./NO0589_grhsim_ir_cpu_gate57_generation_20260907.md)

## Build Result

交接时已启动的全模型构建自然结束，未重启或拼接底层构建命令：

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate57 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate57_full_o3_build.log 2>&1
```

进程退出 0，6255 个模型对象全部编译，模型归档与 XiangShan harness 链接完成。

| 项目 | 结果 |
| --- | ---: |
| Wall time | 11:43.31 |
| User time | 5141.06 s |
| System time | 384.80 s |
| Maximum resident set size | 901212 KiB |
| 模型 archive 字节数 | 189327936 |

模型 archive 为 `ptmp/xs_emit_make_gate57/libgrhsim_SimTop.a`。本次使用既有默认
harness 构建目录，入口 `build/xs/grhsim-ir/emu/emu` 已重新链接到 gate57 模型，
不能再把这个路径当作 gate56 负结果产物。gate55 独立基线入口仍为
`ptmp/xs_gate55_baseline/emu/emu`。所有新增日志和临时目录继续在项目 `ptmp/` 下。

## Validation Boundary

[NO0590](./NO0590_grhsim_ir_cpu_history_batch_hdlbits_gate_20260907.md) 的 162/162
HDLBits 全量回归已退出 0。此次只接续并收齐既有进程的结果，没有启动新的构建、
安装或仿真，没有改动 DPI 的 event 策略、compute 归属和真实调用保留规则。

gate57 尚无实际 XiangShan 运行数据；编译耗时和 archive 缩小都不能替代运行
性能证据。后续仍需 gate57 运行正确性、实际 IR 50k，以及同配置 legacy 50k
性能比较。目标保持未完成。

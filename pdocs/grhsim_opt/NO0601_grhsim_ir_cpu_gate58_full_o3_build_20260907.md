# NO0601 GrhSIM IR CPU Gate58 Full O3 Build

- 日期：2026-09-07
- 前置：[NO0599](./NO0599_grhsim_ir_cpu_gate58_generation_20260907.md)

## Build Result

独立 gate58 通过现有 Makefile 的 build-only 入口完成全模型与 harness 构建：

```sh
/usr/bin/time -v make --no-print-directory xs_wolf_grhsim_ir_build_emu \
  VM_BUILD_JOBS=8 GRHSIM_MODEL_CXXFLAGS='-std=c++20 -O3' WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_IR_BUILD=ptmp/xs_gate58 XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR=ptmp/xs_emit_make_gate58 \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" CCACHE_DIR="$PWD/ptmp/cpu_emit_ccache" \
  > ptmp/grhsim_gate58_full_o3_build.log 2>&1
```

进程退出 0，6255 个模型对象、archive 和独立 emu 全部完成。构建末段通过实际对象
列表确认 task_5615/task_5786 尚在编译，持续等待同一存活进程，没有因日志暂不变化
而重启。所有对象完成后才启动性能运行。

| Metric | Value |
| --- | ---: |
| Wall | 16:46.94 |
| User | 6396.31 s |
| System | 384.40 s |
| Maximum resident set | 923916 KiB |
| Model archive | 182872038 bytes |
| emu | 164234400 bytes |

相较 gate57 的 11:43.31，编译明显变慢；archive 从 189327936 字节仅小幅缩小。
这两项代价必须保留，不能只报告源码或运行中的有利数字。

新运行入口为 `ptmp/xs_gate58/emu/emu`，旧 gate57 默认入口不受影响，不混用 ABI。
HDLBits 162/162 已先行退出 0（NO0600）。运行收益和完整模型功能另行归档。

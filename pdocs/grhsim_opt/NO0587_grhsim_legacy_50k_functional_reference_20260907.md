# NO0587 GrhSIM Legacy 50k Functional Reference

- 日期：2026-09-07
- 关联：[NO0586](./NO0586_grhsim_ir_cpu_gate55_10k_functional_gate_20260907.md)

## Executed Reference

通过已有 legacy 二进制补充后续 IR 50k 对照所需的真实参考轨迹，没有修改或重编译
legacy 实现：

```sh
make --no-print-directory run_xs_wolf_grhsim_emu WOLF_ENV_SOURCED=1 \
  XS_GRHSIM_BUILD=build/xs/grhsim XS_SIM_MAX_CYCLE=50000 \
  XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_LOG_DIR="$PWD/ptmp" \
  XS_PROGRESS_EVERY_CYCLES=1000 RUN_ID=20260907_legacy_50000_reference \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_legacy_50000_reference.log 2>&1
```

进程终态退出 0，NEMU 已启用，没有报告不一致。日志保留 50 个每千周期的进度采样。

- host/model cycles: 50000。
- `instrCnt=73580`、`cycleCnt=49996`、guest cycles 50001。
- 最后 commit PC `0x800012f8`、trap PC `0x80001312`。
- 退出原因：`EXCEEDING CYCLE/INSTR LIMIT`。
- 报告 host time: 172876 ms。

本次与 IR 10k 的后半段并行执行，只作为功能参考，不作为配套 50k 性能基线。
它不能计为 IR 50k 通过，也不意味着 CoreMark 程序执行完成。IR 50k 尚未运行，
后续仍需实际执行并核对 NEMU、指令推进和终态结果。

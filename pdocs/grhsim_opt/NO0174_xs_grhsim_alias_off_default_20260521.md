# NO0174 XS GrhSIM Alias-Off Default

日期：2026-05-21

## 目的

把 `NO0173` 的诊断转成默认运行口径：XiangShan grhsim emit 默认关闭 per-supernode storage-ref alias，避免后续 fresh emit 自动回到 `NO0172` 的慢代码形态。

本次只修改 XS 脚本默认口径，不修改 grhsim emitter 的全局默认行为。

## 改动

修改文件：

```text
scripts/wolvrix_xs_grhsim.py
```

行为：

- 如果用户没有显式设置 `WOLVRIX_GRHSIM_STORAGE_REF_ALIASES`，脚本自动设置为 `0`。
- 如果用户显式设置了该环境变量，脚本保留用户设置，不覆盖。
- emit 日志新增当前口径：

```text
storage_ref_aliases=0(xs_default)
```

或用户显式覆盖时：

```text
storage_ref_aliases=<user_value>
```

## 依据

`NO0173` 显示，在完全相同 activity-schedule 结构下：

| 实验 | sched bytes | 20k gate |
| --- | ---: | ---: |
| `NO0151` alias-off | `1788406953` | `101232 ms` |
| `NO0172` alias-on | `2696952102` | `129095 ms` |

`NO0172` 的结构已恢复，但 runtime 未恢复；主要差异是生成代码重新出现大量 alias：

| 指标 | `NO0151` | `NO0172` |
| --- | ---: | ---: |
| `auto &grhsim_state_scalar` | `0` | `1318475` |
| `auto &grhsim_value_` | `0` | `3184814` |

因此 XS 默认口径应优先回到 `NO0151` 的 clean alias-off 代码形态。

## 验证

已完成轻量验证：

```sh
python3 -m py_compile scripts/wolvrix_xs_grhsim.py
```

结果：通过。

## 待验收

本次没有 fresh emit/build/runtime，因为改动刚刚完成，且此前用户已指出不能无理由 fresh emit。

下一次需要 full emit 时，应同时验收：

- emit log 中出现 `storage_ref_aliases=0(xs_default)`。
- sched 源码体积回到 `NO0151` 级别，而不是 `NO0172` 的 `3.0G` 级别。
- 20k gate 接近 `NO0151/NO0152` 的 `~99-101s` 档。
- 如果 20k 未接近该档，再继续查 emitter 代码形态差异。

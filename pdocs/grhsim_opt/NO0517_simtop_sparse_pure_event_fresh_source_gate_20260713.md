# NO0517 SimTop sparse pure-event fresh source gate

日期：2026-07-13

## 1. Preflight and fresh flow

按 [NO0516](./NO0516_simtop_sparse_pure_event_fresh_source_plan_20260713.md) 对子仓库 `0c37785` 执行 editable reinstall。
Python extension 的 `ldd` 指向当前 `.venv` 内 `libwolvrix-lib.so`，library strings 包含 sparse-batch opaque predicate 新文本。

输入 SHA256：

```text
pre-reg checkpoint b95afe35eb8533c00da7d7d6867d72a626cde908ef8af94700a48d0124ea90a1
read args          bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c
```

输出与日志：

```text
build/xs_grhsim_no0516_sparse_pure_event_20260713/grhsim/grhsim_emit
build/logs/xs/xs_wolf_grhsim_build_no0516_sparse_pure_event_emit_20260713.log
```

主机 load 为 `178.38/192.28/181.88`，available memory 约 `600 GiB`。本阶段不是 runtime 测试。fresh flow 成功退出：

```text
read checkpoint         59.546 s
reg-to-mem             260.936 s
activity schedule      160.120 s
C++ emission            76.764 s
reported total         557.370 s
wall clock             561.31  s
peak RSS                27.77 GiB
exit status              0
```

## 2. Structure identity

schedule stats SHA256 仍为：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

最终结构保持 compute/commit supernodes=`63,241/485`、DAG edges=`528,622`、boundary values=`1,000,463`、BAE=
`1,983,923`。direct-state-read 仍为 reads/canonical/aliases=`75,830/40,108/35,722`，removed source heads/consumer
heads=`37,672/39,602`。

## 3. Production predicate shape

对所有 sched source 按 marker 后第一条 outer `if` 解析：

```text
markers / files               107 / 22
volatile hits / files          20 / 14
hit wrappers                   20
direct exact-event wrappers    87
malformed wrappers               0
```

14 个 sparse batches 精确为：

```text
12,16,18,20,22,24,25,27,37,50,51,56,57,61
```

这与 NO0513 的 threshold-2 audit 完全一致。profile arrays/counters/getter/dump 与非 volatile shared hit 均为零。

## 4. Source identity and diff closure

NO0357 baseline、NO0501 plain bypass 与本轮 hybrid 均有 `154` 个 `.cpp/.hpp`。逐文件 SHA256 对照得到：

- hybrid 相对 NO0501 只改变上述 14 个 sched files，另外 `140` 个文件 byte-identical；
- hybrid 相对 NO0357 仍只改变原有 `22` 个 eligible sched files，另外 `132` 个文件 byte-identical；
- 8 个 dense eligible sched 与 NO0501 byte-identical，因此 hot 35/58/21 保持 direct codegen source；
- hybrid vs NO0501 diff 为 `+60/-20`：20 条删除全部是 direct outer equality；新增严格为 20 条 opaque comment、20 条
  volatile temporary、20 条 hit wrapper；原 entry、payload、inner guard、restore、closing brace 删除为零。

生成源总字节数：

| Model | Bytes | Delta vs NO0357 |
| --- | ---: | ---: |
| NO0357 baseline | 1,357,263,998 | 0 |
| NO0501 plain bypass | 1,357,283,472 | +19,474 |
| NO0516 sparse hybrid | 1,357,287,512 | +23,514 |

## 5. Decision

fresh SimTop source gate 通过。下一步使用该 154-file model 执行标准 Clang O3 archive/emu build，并分别比较 NO0357 baseline 与
NO0501 plain binary/object 指标；只有 build/link 和静态 codegen 闭合后才进入 100/10k/50k 功能门禁。

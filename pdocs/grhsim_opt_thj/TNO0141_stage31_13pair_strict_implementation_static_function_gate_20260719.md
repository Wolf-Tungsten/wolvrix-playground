# TNO0141 Stage 31 13-pair strict implementation, static, and function gate

日期：2026-07-19

状态：独立显式策略 `cofire-strict-extended` 已完成实现、production emit、O3/archive、
emu link、fresh NUMA staging 和 control/12-pair/13-pair 的 100/10k/50k 功能门禁。
13-pair candidate 功能正确，实际删除 `691` 个 source-side tracked values，global work
由 `2,417,244` 降至 `2,415,848`；但正式端到端结论必须等
[TNO0142](./TNO0142_stage31_13pair_strict_formal_walltime_block_and_default_decision_20260719.md)
的完整 balanced `Host time spent`，本篇单次功能 walltime 不作性能结论。

## 1. 实现边界

- 保留 Stage30 `cofire-strict` 精确等于原 12 对；新增
  `cofire-strict-extended`，只追加 `35026 -> 38043`。
- C++、native binding、Python binding 和 XS 显式环境变量均识别新策略；C++ 默认仍为
  `off`，XS 没有另设默认参数。
- 两个 strict policy 共用 lowering，但分别选择固定长度 12/13 的 immutable spec span；
  active ID、batch、op count、50k fire、value count/fingerprint 或 profile shape 任一变化
  都 fail-closed。
- extended 继续只覆盖 ordinary compute 的 changed-value/deferred lowering；fullpass、
  commit、seed、graph、schedule、slot、active ID 和 batch 都保持 baseline。
- pair13 的 target 是 86 个纯 `kLogicAnd`。允许 Stage29 已观察到的 141 次 leader miss；
  purity、source-before-target 和 difftest 共同约束功能正确性，不把 cofire 当作功能前提。

相关实现位于 `wolvrix/lib/emit/grhsim_cpp.cpp`，配置透传位于 native/Python binding；
focused C++、Python 和 XS tests 同步覆盖 invalid policy、wrong profile/pair set 和与 active
mask gap policy 的互斥 gate。

## 2. Production emit 与严格 accounting

production raw log：

```text
build/logs/xs/stage31_strict_extended_final_20260719.log
sha256=5d178da77da94af49d7bd179c160a9e587a88b06855ca51a5c119ea4ce68d90f
bytes=278207
elapsed=4:37.90
exit_status=0
```

日志逐项打印 13 个 value fingerprint；新增 pair13 为：

```text
pair=12 source=35026 target=38043 count=43 fingerprint=91cd730c99b00052
```

严格局部 accounting 的绝对值为：

| field | control | 13-pair overlay | delta |
| --- | ---: | ---: | ---: |
| tracked change values | 1,334 | 643 | -691 |
| direct value groups | 339 | 336 | -3 |
| deferred groups | 101 | 89 | -12 |
| deferred source updates | 1,307 | 619 | -688 |
| deferred direct groups | 101 | 89 | -12 |
| forward groups | 0 | 13 | +13 |
| active-mask entries | 523 | 521 | -2 |
| planned chunks | 442 | 440 | -2 |
| branchless groups | 440 | 425 | -15 |
| conditional mask updates | 442 | 427 | -15 |
| global RMW | 442 | 440 | -2 |
| updated bytes | 523 | 521 | -2 |
| estimated activation lines | 442 | 466 | +24 |
| work units | 3,525 | 2,129 | -1,396 |

raw validation 为 `validated=true pairs=13 values=691`，最终 overlay 行同时确认
`fullpass_excluded=true commit_excluded=true seed_excluded=true`。

production log 中 `DEFERRED_ACTIVATION_FORWARD accounting=candidate` 仍是 Stage28 broad
128-pair probe，不是实际写入 CPP 的 extended overlay。把上表 local delta 应用到同日志
的 global control，实际 13-pair 全局 accounting 为：

```text
work_units                  2417244 -> 2415848
tracked_change_values        752375 -> 751684
direct_value_groups          140145 -> 140142
deferred_groups              136969 -> 136957
deferred_source_updates      925811 -> 925123
deferred_direct_groups       135682 -> 135670
forward_groups                    0 -> 13
active_mask_entries          420843 -> 420841
planned_chunks               396572 -> 396570
branchless_groups            265317 -> 265302
conditional_mask_updates     327748 -> 327733
global_rmw                   399483 -> 399481
updated_bytes                418250 -> 418248
estimated_activation_lines   549155 -> 549179
```

因此 static work 是绝对减少 `1,396`，estimated activation lines 是绝对增加 `24`；
两者都是解释性指标，不能替代 walltime。

## 3. Generated CPP 对账

相对 current-default control，只有 9 个 schedule CPP 改变：

| schedule CPP | control bytes | extended bytes | delta |
| --- | ---: | ---: | ---: |
| `11` | 29,268,760 | 29,257,580 | -11,180 |
| `28` | 15,017,651 | 15,008,707 | -8,944 |
| `52` | 16,481,482 | 16,470,290 | -11,192 |
| `53` | 13,068,529 | 13,046,221 | -22,308 |
| `54` | 12,351,388 | 12,329,004 | -22,384 |
| `56` | 14,143,796 | 14,132,616 | -11,180 |
| `57` | 13,563,137 | 13,551,957 | -11,180 |
| `59` | 14,553,166 | 14,519,626 | -33,540 |
| `60` | 13,035,601 | 13,024,421 | -11,180 |
| 合计 | 141,483,510 | 141,340,422 | -143,088 |

其中只有 schedule 28 相对 Stage30 12-pair 再改变，大小
`15,017,651 -> 15,008,707`，即 pair13 单独减少 `8,944` bytes。按生成源码中的
`grhsim_changed_<ValueId>` unique set 对账，control=`613,454`、extended=`612,763`，
removed=`691`、added=`0`。

以下非 schedule 产物与 control SHA 相同：

```text
grhsim_SimTop.hpp                  8022ea29a39ce82cd6f46fc4d2bb49d8cbc29b57d97459696710500d40f8da6d
grhsim_SimTop_eval.cpp             4d99029805f5ed72dd3de5200775a8b44969ea1265d985479cce8a37e1a072cc
grhsim_SimTop_runtime.hpp          07484074f859abd94f71fef13aaf6ab5b6d8c1f65d23d0e1d6333a5e4bd4d8ff
grhsim_SimTop_state.cpp             70f2cdae4c6fe903525ebfc52253aff1817e4169af3493439016c5d50d969dbe
activity_schedule_supernode_stats  6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c
grhsim_emit_stats.json              9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b
```

## 4. O3、link 与二进制绝对值

O3/archive raw log：

```text
build/logs/xs/stage31_strict_extended_final_o3_clang_build_20260719.log
sha256=fa821c294f4d6f5deb1acd588bde24d72f1e7a25bdfa1fa0bb7cbeeded33aff8
bytes=24825
exit_status=0
```

archive 绝对值：

```text
bytes=99233198
sha256=5eed2861ec9b244c7f6ab5bec9b498d7cdfd78ca7ff00f9edbedee0f2e52fadc
```

emu link raw log SHA=`954b4cb9ebaafdf4590a2d62790c5e662f0ba3c0907ffa518aa09e61107997d9`，
大小 `5,624` bytes，退出 0。extended emu：

```text
bytes=93655432
text=93478495
sha256=ad3ca84ef72590139fc245654cd995f472beb9efd550162870cfa37ef86047b1
```

相对 Stage30 12-pair `.text=93,479,439`，pair13 再减少 `944` bytes；相对 control
`.text=93,495,071`，总差 `-16,576` bytes。

## 5. Fresh NUMA staging 与功能门禁

staging 根目录为：

```text
/dev/shm/tanghaojin_stage31_cofire_extended_20260719_v1
```

N0 使用 CPU43/NUMA0，N1 使用 CPU139/NUMA1；每个 node 上的
control/strict12/strict13/coremark/NEMU 都由目标 node 的
`taskset + numactl --physcpubind/--membind cp --reflink=never` first-touch 成为独立
inode。manifest：

```text
build/logs/xs/stage31_strict_extended_staging_stat_sha_20260719.log
sha256=e0985a81e63a33865d2bd35062a5446d471b9ed6a77b8fc7cd7adddc0f0cfaa8
bytes=6032
```

N0 inode 为 `5506..5510`，N1 为 `5511..5515`；每个 staged file 的源/目标 SHA 与
`cmp=PASS` 都在 manifest。三种 emu 的绝对 SHA/bytes 为：

| variant | bytes | SHA256 |
| --- | ---: | --- |
| control | 93,671,816 | `31ab2b820cbce126199b7baef5d9f15909f6db1e39bb72d1b140bc398924ba65` |
| strict12 | 93,655,432 | `c2fbd21b379c2d7ae9d2b930386a3130254045bbbab3bfeefa311e2bebf0ac0b` |
| strict13 | 93,655,432 | `ad3ca84ef72590139fc245654cd995f472beb9efd550162870cfa37ef86047b1` |

功能命令固定为：

```text
taskset -c 43 numactl --physcpubind=43 --membind=0 \
  setarch x86_64 -R <staged-emu> -i <staged-image> --diff <staged-nemu> \
  -b 0 -e 0 -C <100|10000|50000>
```

9 个 raw log 均 exit 0，无 mismatch/assert/fatal；绝对功能终点和单次诊断 walltime：

| cycles | instrCnt/cycleCnt/guest | control wall | strict12 wall | strict13 wall |
| ---: | --- | ---: | ---: | ---: |
| 100 | `0 / 96 / 101` | 143 ms | 141 ms | 145 ms |
| 10,000 | `458 / 9,996 / 10,001` | 9,455 ms | 9,446 ms | 9,464 ms |
| 50,000 | `73,580 / 49,996 / 50,001` | 74,270 ms | 74,179 ms | 74,317 ms |

raw log 的 SHA/bytes：

| variant/count | bytes | SHA256 |
| --- | ---: | --- |
| control/100 | 684 | `3309d6ae1fd521125c3907708c286be17fca7668ddd3bc4c93caae4ec6877331` |
| control/10000 | 824 | `80554a36fef910d6de4096814f506bfb15fb81c4fcbf7b03aeea6672846a1543` |
| control/50000 | 1,026 | `39f22159a517f1c47477c36279b852c07f68e705f222472377570a57b68fe77e` |
| strict12/100 | 686 | `f53b36417b7f74604b77be02d940007f3cf9fd0c62495b907aab688fca94bb4d` |
| strict12/10000 | 826 | `df532e4c537770f1360be43d7ad00c5acda98c7ad2e77c50054f278023aaf6f9` |
| strict12/50000 | 1,028 | `169737b04f5423bce21ef9cc7c4e2688ee1aab9247404ff23ad07d18f3e95d7b` |
| strict13/100 | 686 | `f544d2d7e00272b7500e406c96fce78b0f3ed6288199a1aafee9ee8fd11c30db` |
| strict13/10000 | 826 | `03cb4d60102c71eab374284672596add1bcf5b9449f6fd79b9cac4588d8cd3b7` |
| strict13/50000 | 1,028 | `8ca2cb491fb80f678ca52c8126ba6a1935862ce5d7b631391bd2c2b52baeb018` |

这些功能运行没有 formal whole-node admission/monitor，因此即使保留了绝对
`Host time spent`，也不能进入端到端 A/B 均值。

## 6. Regression gate

- fresh rebuild 成功；`emit-grhsim-cpp-deferred-activation-forward` 通过。
- Python binding option tests `12/12` 通过；XS option forwarding tests `25/25` 通过。
- full CTest 为 `47/49`；仅有长期既有失败
  `transform-comb-lane-pack` 和 `transform-repcut`，错误文本与 Stage11..30 raw logs 相同，
  本阶段未修改对应 transform/test 文件。
- `emit-grhsim-cpp` full test 通过，耗时约 295 秒；没有新增 Stage31 相关失败。

完整 CTest 和 Python/XS raw log 的 SHA/大小在重跑完成后由同阶段提交记录补充；最终
采用与否仍只由 TNO0142 的 formal walltime 决定。

## 7. Regression raw log 增量补充

上述重跑已经完成。本节给出原始产物并 supersede 第 6 节最后一句的“待补”状态。

```text
build/logs/stage31_full_ctest_20260719.log
sha256=08f76a87bd5f25a63792d51f1e9df199b78cf4138798cd957190efda22cbce7d
bytes=6633
tests=47/49 passed
exit_status=8
```

`emit-grhsim-cpp` 在该 raw log 中通过，耗时 `296.82 sec`。两个失败及绝对错误文本为：

```text
transform-comb-lane-pack: Expected one packed kAnd for storage frontier rewrite
transform-repcut: expected repcut partition static feature export
```

这两项在 `stage26_full_ctest_after_rebuild_20260718.log`、
`stage27_full_ctest_20260718.log` 及更早 Stage11..25 raw logs 中同样失败；本阶段没有改动
对应 transform 源码或测试，因此登记为 pre-existing，不是新增回归。

Python/XS raw log：

```text
build/logs/stage31_python_xs_option_tests_20260719.log
sha256=c1af95934ca34495bcbc3fac8f6b91dec4293397c3c69783bc966ff6df08ac5f
bytes=249
Python options=12/12 passed
XS forwarding=25/25 passed
exit_status=0
```

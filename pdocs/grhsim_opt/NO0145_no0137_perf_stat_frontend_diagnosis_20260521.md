# NO0145: NO0137 perf-stat frontend diagnosis

> 从 `NO0093_essent_mffc_activity_schedule_plan_20260518.md` 拆出的独立实验记录，避免继续把多轮实验追加成单个长文档。


背景：

- NO0128/NO0137 之后，多数单 helper 代码形态优化都只带来边际收益或负收益。
- 本轮对当前好档位 NO0137 emu 做 20k `perf stat`，确认下一步是否应继续追 helper，还是应转向 generated code 前端压力。

命令：

```bash
perf stat -o tmp/no0145_perf_diagnosis/no0137_coremark20k_perf_stat.txt \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses,dTLB-loads,dTLB-load-misses,iTLB-loads,iTLB-load-misses \
  env EMU_PROGRESS_EVERY_CYCLES=10000 \
  tmp/no0137_xs_gated_mux_and_emu/grhsim-compile/emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 20000
```

结果：

- CoreMark 20k：
  - 10k: `host_ms=23219`
  - 20k: `host_ms=99327`
  - `Host time spent=99334ms`
  - 退出码 `0`，未出现 difftest mismatch。
- perf stat：
  - `cycles=566392725547`
  - `instructions=98199646994`
  - `IPC=0.17`
  - `branches=11034965429`
  - `branch-misses=4202516071`
  - `branch-miss-rate=38.08%`
  - `cache-references=30676255825`
  - `cache-misses=14326871572`
  - `cache-miss-rate=46.70%`
  - `dTLB-load-misses=757965`
  - `dTLB-load-miss-rate=0.12%`
  - `iTLB-loads=841701972`
  - `iTLB-load-misses=442573976`
  - `iTLB-load-miss-rate=52.58%`

判断：

- 当前好档位的硬件画像不是单个 wide helper 或动态分配独占瓶颈，而是巨大 generated code 的前端压力：
  - IPC 极低。
  - branch miss 极高。
  - iTLB miss 极高。
- 后续优先级应转向减少 generated code footprint / batch 前端压力，例如：
  - 对 NO0137 同源产物尝试 `-O2` model build，验证是否代码膨胀导致 `-O3` 负担过重。
  - 继续压缩 commit/compute batch 代码体，但不能像 commit cap1024 那样增加 BAE。
  - 对热点 commit batch 做更细的 profile，找 repeated branch/mask pattern，而不是继续按静态 helper 调用数做微优化。


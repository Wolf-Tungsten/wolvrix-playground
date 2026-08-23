# A0089 step：r004/t1/s01 guard 缓存与 concat 位置装配（2026-08-23）

对应 `next` = `step-resume`，轨迹 `t1`，step 1/4，K=2。`begin-step` 与 c1/e00089
已在恢复前完成；本次只补做 pending `[2]`，没有重复 begin-step、没有重跑已登记候选，
也没有手改 `run.json`。Phi 唯一来源为 r004 AM 基线 e00085（commit `1563c3d837fc`，
Host **193.403s**，完整 12 开关表型）。两项候选分别处理 A0088 recon 的 task
守卫池与 scalar Concat 池，机制互异。

## 候选与结果

| 候选 | eval / commit | 来源 -> 动态病灶 -> 局部改动 -> 可证伪预期 | 正式结果 | 裁决 |
|---|---|---|---|---|
| c1 `--host-call-guard-cache` | e00089 / `784a466` | e00085 -> b90656/b90657 执行 88,260/100,791 次、合计占总块 cycles **4.629%**，相邻 immediate fwrite/DPI 站重复读取相同 fire/event -> 每个 block chunk 对连续同条件站只计算一次完整 guard；排除 pending/once/final 及会写 guard operand 的调用 -> 若重复成员读取是一阶成本，应越过 3% noise 门 | **190.827s**（190.827/185.959/192.048s，CV 1.70%，单簇、非 noisy），`compile_s=640.3s`；17/17 ctest，3 rep difftest 均为 73580/49996；较 e00085 名义 **-1.33%** | raw-score winner；`finish-step` outcome=`initial`，未越 3% 门 |
| c2 `--concat-position-pack` | e00090 / `ed82b83` | e00085 -> b83835/b93085 合计占总块 cycles **2.354%**，生成代码含密集 scalar `concat_value` 前缀链 -> 对 <=64-bit Concat 将各 operand mask 后直接放到最终 shift，Replicate 与宽 Concat 不变 -> 若累计前缀的串行 mask/shift 是可见成本，应越过 3% noise 门 | **191.508s**（191.508/189.225/193.535s，CV 1.13%，单簇、非 noisy），`compile_s=638.5s`；17/17 ctest，3 rep difftest 均为 73580/49996；较 e00085 名义 **-0.98%**，同窗较 c1 **+0.36%** | 未越 3% 门；非确认收益，未入主线 |

两个 `tes-candidate.json` 都声明相对冻结父表型的单一增量；正式 evaluator 显式传入
12 项父开关再追加候选开关，两个 `result.json.emit_args` 均与声明逐项一致。生产
engagement 核对显示 c1 形成 **6,314** 个共享 guard 组；c2 将 **213,894** 个 scalar
Concat 的 **699,997** 个 operand term 改成最终位置装配。b83835/b93085 中分别有
2,846/2,098 个位置装配 term；b83835 其余 `concat_value` 调用来自未改动的 Replicate。
c2 自测同时覆盖默认 helper 链、开启后的 63/56/48/32/0 最终 shift，以及 stock/packed
两份生成模型的编译运行等价。

## 裁决与机制分析

- 两次正式评估严格串行且只通过任务 evaluator；每项均在独立 wbuild/emu_build 完成
  全量构建、17 项回归、金标 difftest 和绑核 3 rep。两批每个 rep 的起跑 loadavg
  形态接近（c1 48.73/3.03/1.14，c2 54.55/3.10/1.15），可作 raw 排名；但 0.36%
  差值远小于 r004 的 3% adjudication noise，不能确认 c1 优于 c2 的机制幅度。
- c1 覆盖 recon 指出的 4.629% task 双峰池，缓存完整 guard 后只得到 1.33% 名义改善。
  这与“重复 guard 读取有小幅成本”相容，却不足以证明因果收益；进一步精修前应先用
  新 recon 检查 b90656/b90657 权重是否下降，并量化 cache group 的动态命中率。
- c2 虽改写 21 万余个 scalar Concat，但 `concat_value` 本来就是生成头文件中的
  `static constexpr`，累计宽度也全是编译期常量，O3 已有机会内联并折叠 helper 链。
  直接位置装配减少了源码级前缀依赖，却只得到 0.98% 名义改善，说明静态调用数并非
  剩余 Host 成本的可靠代理；没有新的块级或汇编证据前，不继续做 scalar concat
  语法形态精修，也不外推到 Replicate/宽 Concat。
- `finish-step` 按 raw score 将 e00089 快移到 `tes/r004/t1/main`，作为 t1 的首个
  `initial` 节点。这不是 `outcome=win`；t1 AM/gsim 口径为 **8.399x**，仍慢于全局
  best t0/e00088 的 **8.355x**，目标远未达到。

## 后续建议

t1 再次到期时先对 e00089 做新 recon；只有 b90656/b90657 的动态权重下降或 guard
命中率证明足够高，才继续 guard-cache 邻域，否则关闭该语法级方向。scalar Concat
方向在获得热点块汇编或逐操作族动态成本前不再占候选席位，也不把 e00090 作为迁移
来源。预计状态机下一 action 为 **t2/e00085 recon**（非计时 profiling）；本 action
只预告，不启动它。

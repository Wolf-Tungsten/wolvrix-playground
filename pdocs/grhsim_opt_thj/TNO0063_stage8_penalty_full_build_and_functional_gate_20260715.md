# TNO0063 Stage 8 penalty full build and functional gate

日期：2026-07-15

状态：p050/p200 均完成 full emit、O3 build 与 fixed-ASLR 100/10k 功能门禁；full stats 精确复现结构扫描，50k 纳入后续跨 NUMA 正式 runtime 文档。

## 1. Full emit

按 [TNO0062](./TNO0062_stage8_plain_dp_penalty_structure_scan_20260715.md) 的候选决策，从同一个 post-reg-to-mem checkpoint 分别以 `500000/2000000 PPM` 重跑完整 activity schedule 和 GrhSIM C++ emit。其余配置继续显式锁定为仓库默认 NO0300，direct/bypass/profile/packing/post-DP/Kahn/local clone 均关闭，ASLR 在 runtime 关闭。

两套 full emit 均 exit `0`，单套 emitter 约 `53.4s`。full stats 逐项复现结构扫描：

| 候选 | total/compute/commit SN | DAG | boundary values | total BAE | compute/commit pairs |
| --- | --- | ---: | ---: | ---: | --- |
| p050 | `63903/63418/485` | 529017 | 1000466 | 1983746 | `1721521/262225` |
| p200 | `63583/63098/485` | 528510 | 1000471 | 1984205 | `1721980/262225` |

产物目录：

```text
build/xs_activity_stage8_dp_p050_20260715/grhsim/grhsim_emit
build/xs_activity_stage8_dp_p200_20260715/grhsim/grhsim_emit
```

## 2. Fresh O3 build

两套隔离 `BUILD_DIR` 直接调用 XiangShan difftest `emu` target，使用 `clang++ -std=c++20 -O3`；均成功归档 model objects、完成最终链接并 exit `0`。

与 Stage 7 fresh NO0300 rollback 控制比较：

| 指标 | NO0300 control | p050 | p050 delta | p200 | p200 delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| generated source files | 154 | 155 | +1 | 153 | -1 |
| schedule CPP | 117 | 118 | +1 | 116 | -1 |
| generated source bytes | 1377536436 | 1377308861 | -0.016520% | 1377679214 | +0.010365% |
| generated source lines | 13911084 | 13910332 | -0.005406% | 13911259 | +0.001258% |
| emu bytes | 94768184 | 94702408 | -0.069407% | 94740328 | -0.029394% |
| emu `.text` | 88186297 | 88115600 | -0.080168% | 88149251 | -0.042009% |

p050 虽多一个 schedule CPP，源码和 `.text` 反而略小；p200 少一个 schedule CPP，但源码 bytes 略增而 `.text` 略小。两者都说明 segment 数变化会触发 batch/layout 重分组，不能从 SN、源文件数或源码 bytes 单项推出 runtime 方向。

O3 emu SHA256：

```text
NO0300  cd093aadefee6e84e236d8826558e6bc9beeebaee41f2133bf6dc57c0457fe97
p050    f716ed8511c6875957dd2d3fad9715f54d9c6c07d738c4bcc395a519b8643dc5
p200    adcde341a5aa9659c88b4a36ef8346f89db5702a3651527425e8e6b0cc671c3f
```

## 3. Fixed-ASLR functional gate

p050/p200 均在 `setarch x86_64 -R` 下完成 100/10k：

| 候选 | limit | guest/cycle/instr | PC | exit |
| --- | ---: | --- | --- | ---: |
| p050 | 100 | `101/96/0` | `0x0` | 0 |
| p050 | 10000 | `10001/9996/458` | `0x800027c6` | 0 |
| p200 | 100 | `101/96/0` | `0x0` | 0 |
| p200 | 10000 | `10001/9996/458` | `0x800027c6` | 0 |

四份日志的 mismatch/assert/error/fail/bad-trap 负向扫描为 `0`。50k 不另做高负载 wall 计时，直接由 formal quiet A/B/A 样本同时闭合功能终点和最终性能。

## 4. 当前结论

两侧候选均无明显结构、代码体积或功能退化，继续进入 SimTop 50k。静态结果不足以修改默认；仓库默认 penalty 仍为 `1000000 PPM`。

# TNO0153 Stage 33 strict full regression gate

日期：2026-07-19

状态：final code 完整 build exit0，串行 full CTest=`48/50`、`403.44 s`。两项失败与
Stage31/32 既有集合完全相同，Stage33 新增 same-batch strict、deferred neighbor、完整 emitter、
memory-fill、activity schedule、全部 ingest 均通过，没有新增回归。

## 1. Build

执行：

```text
source env.sh
cmake --build wolvrix/build -j4
python3 -m pip install --no-build-isolation -e wolvrix
```

build 与 editable wheel/install 均 exit0。CMake 对若干 `compiler_depend.make` 报约
`0.002..0.008 s` future timestamp/clock-skew warning，但所有 target 完成，随后 full CTest 和
production emit 均使用了新 strict marker/FNV，不能解释为 stale extension。editable wheel
size=`24,348,496 B`，install success。

## 2. Full CTest

执行：

```text
ctest --test-dir wolvrix/build -j1 --output-on-failure
```

绝对结果：

```text
total=50
passed=48
failed=2
pass_rate=96%
wall=403.44 s
```

最终 raw log：

```text
build/logs/xs/stage33_same_batch_cohort_strict_20260719/full_ctest_final.log
sha256=8ee7553dbb47b9f447b7a188215d55cc6bca179e22794b334de227a0b4cd9d6f
bytes=6815
```

关键通过项：

| test | result | time |
| --- | --- | ---: |
| full `emit-grhsim-cpp` | PASS | `294.45 s` |
| deferred activation forward | PASS | `0.38 s` |
| same-batch activation cohort | PASS | `13.34 s` |
| emitter memory fill | PASS | `4.82 s` |
| activity schedule | PASS | `0.20 s` |
| ingest stmt lowerer | PASS | `33.94 s` |
| ingest memory port lowerer | PASS | `21.31 s` |

其余 GRH/store/SV emit/transform/ingest tests 也全部通过。

## 3. Known failure identity

| test | absolute error | Stage33 ownership |
| --- | --- | --- |
| `transform-comb-lane-pack` | `Expected one packed kAnd for storage frontier rewrite` | 既有失败；Stage33 未改 transform |
| `transform-repcut` | `expected repcut partition static feature export` | 既有失败；Stage33 未改 transform |

失败文本与 Stage31/32 相同。Stage33 变更只涉及 GrhSIM emitter strict lowering、对应
Python/native validation 和 focused tests；没有触碰两个失败 target 的实现或 fixture。

## 4. Gate conclusion

Stage33 implementation/static/function 阶段可以按 submodule-first 提交。该提交只表示
default-off candidate 正确性与可复现实验入口闭合；默认仍为 C++ `off`，性能采用结论必须等
fresh same-commit control 的正式双 NUMA 50k `Host time spent`。

# NO0080 GrhSIM Compact Local Expr Emit

## 背景

`NO0079` 的 BigComb one-supernode 实验显示，`grhsim_BigComb_sched_0.cpp` 明显大于 `gsim` 的 `BigComb0.cpp`。本轮先针对 `grhsim` 的非物化局部值生成做低风险压缩，不改变 state / DPI / commit 写回语义。

## 改动

- 非物化 local value 名称从 `local_value_<id>_<gen>_<symbol>` 缩短为 `grhsim_v<id>_<gen>`。
- `SupernodeLocalExprContext` 增加当前 supernode / phase 内的 operand use-count。单用户 inline 判定优先使用这个局部 use-count，而不是全图 `Value::users()`。
- 单用户标量表达式 inline 阈值从 `160` 提高到 `1024`，并允许 mux 产生的 `?:` 表达式参与 inline。
- 标量拼接 / replicate / operand cast 路径避免部分重复 `static_cast<std::uint64_t>(static_cast<std::uint64_t>(...))` 包裹。
- 后续继续压缩调度代码形态：
  - 非物化 value 不再输出 `// value` 注释，普通 compute op 不再输出 `// op` 注释，只保留 boundary / materialized / change-tracked op 注释。
  - `scalarTruncExpr` 识别零常量、已同宽 mask 的表达式和冗余 `static_cast<std::uint64_t>(...)`，避免重复 trunc / cast。
  - concat / replicate 的 masked operand 路径递归剥离冗余窄类型 cast。
  - 非 inline 局部 scalar 改为 `const <cppType> v = <bounded expr>`，不再用 `const auto v = static_cast<T>(...)`。

## BigComb One-Supernode 静态结果

输入仍使用 `testcase/big-comb` 的 one-supernode 配置：

```text
GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE=200000
GRHSIM_SCHED_BATCH_TARGET_COUNT=1
GRHSIM_SCHED_BATCH_MAX_OPS=10000000
GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES=10000000
```

对比文件：

```text
old: testcase/big-comb/build-one-supernode/grhsim/model/grhsim_BigComb_sched_0.cpp
new: testcase/big-comb/build-one-supernode-compact3/grhsim/model/grhsim_BigComb_sched_0.cpp
gsim: testcase/big-comb/build-one-supernode/gsim/model/BigComb0.cpp
```

| 文件 | 行数 | 字节 |
| --- | ---: | ---: |
| old grhsim sched_0 | 489106 | 55838017 |
| new grhsim sched_0 | 279182 | 36166900 |
| gsim BigComb0 | 445168 | 25206100 |

精确 token 统计：

| 指标 | old grhsim | new grhsim |
| --- | ---: | ---: |
| local value refs | 418314 | 103428 |
| `const auto` | 123403 | 18441 |
| `static_cast<` | 565918 | 565918 |
| comment / blank lines | 364269 | 259307 |

结论：

- 第一版紧凑化主要消掉显式局部变量流：源码大小下降约 `35.22%`，行数下降约 `42.92%`，`const auto` 数量下降约 `85.06%`。
- `static_cast<` 数量没有下降，说明表达式内部的 cast/trunc 形态仍是下一层主要冗余。
- 新版 `sched_0.cpp` 已用 `clang++ -O0 -std=c++20` 编译并归档通过。未重新尝试 one-supernode `-O3`，避免重复触发长时间编译。

## 继续压缩结果

在第一版 compact local expr 基础上，继续针对注释、重复 mask、冗余 `uint64_t` cast、窄类型 cast 和 inline cache 表达式做保守压缩。最终对比仍使用同一个 BigComb one-supernode 输入。

| 版本 | 行数 | 字节 | local value refs | `const auto` | `static_cast<` | comment / blank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| old grhsim | 489106 | 55838017 | 418314 | 123403 | 565918 | 364269 |
| compact3 | 279182 | 36166900 | 103428 | 18441 | 565918 | 259307 |
| compact7 | 19225 | 16933214 | 83561 | 17751 | 252932 | 40 |
| compact8 | 17497 | 13651716 | 80105 | 16023 | 241924 | 40 |
| compact9 | 12231 | 8964846 | 69573 | 10757 | 130658 | 40 |
| compact10 | 12231 | 8802093 | 69573 | 116 | 121661 | 40 |
| compact11 | 12135 | 8728601 | 69381 | 116 | 119358 | 40 |
| compact12 | 9305 | 6246674 | 63721 | 116 | 42713 | 40 |
| compact13 | 12135 | 8728601 | 69381 | 116 | 119358 | 40 |
| gsim BigComb0 | 445168 | 25206100 | n/a | n/a | n/a | n/a |

说明：`compact12` 曾尝试让 scalar inline cache 保存去掉外层窄类型 cast 的 bounded raw expression，静态体积继续下降，但重链 benchmark 后在 `vector=1` 出现 gsim/grhsim 输出 mismatch，因此该版本不能作为正确优化结果。最终有效版本为 `compact13`，它保留 inline cache 中的显式 result-type cast，只在非 inline 局部变量 initializer 和 bit operand 路径做保守压缩。

最终 compact13 相对 old grhsim：

- `sched_0.cpp` 字节数从 `55.84MB` 降到 `8.73MB`，下降约 `84.37%`。
- 行数从 `489106` 降到 `12135`，下降约 `97.52%`。
- `const auto` 从 `123403` 降到 `116`，基本消除非必要局部临时声明。
- `static_cast<` 从 `565918` 降到 `119358`，下降约 `78.91%`。
- 生成代码文本已经明显小于 gsim 的 `BigComb0.cpp`：`8.73MB` vs `25.21MB`。

剩余 `static_cast<` 主要来自：

- 调度入口 active bitset 的 `uint8_t` word 操作。
- 标量算术 / 比较前必要的 `std::uint64_t` 提升。
- 少量 runtime helper 调用参数类型边界。

当前结论：

- 之前 grhsim one-supernode 对象偏大的主要原因不是 supernode 调度本身，而是生成表达式过度物化、注释占比过高、重复 trunc/mask/cast 和 inline 展开携带窄类型 cast。
- compact13 后，BigComb one-supernode 的 grhsim 生成 C++ 文本不再大于 gsim；下一步性能差异应重新回到运行时代码路径和最终优化后汇编验证，而不是继续用源文件体积解释。

## 单 Supernode 性能重测

重测口径：

- gsim 仍使用 `testcase/big-comb/build-one-supernode/gsim` 的既有 `-O3` 对象；
- old grhsim 使用 `testcase/big-comb/build-one-supernode/grhsim/model/libgrhsim_BigComb.a`；
- compact13 grhsim 使用当前 emitter 重新生成 `testcase/big-comb/build-one-supernode-compact13/grhsim/model`，并用 `clang++ -O3 -std=c++20` 重建；
- 两个 benchmark 都用同一份 `tb/big_comb_bench.cpp`，参数均为 `--vectors 1000000 --verify 4096`。

Smoke / 正确性：

```text
compact12 smoke:
[FAIL] mismatch vector=1

compact13 smoke:
[VERIFY] vectors=1000 status=pass
```

1M 正式重测：

```text
old one-supernode:
[VERIFY] vectors=4096 status=pass
[BENCH] model=gsim   vectors=1000000 ms=12330.960 vectors_per_s=81096.69 checksum=0x92cd1159a6bbfc47
[BENCH] model=grhsim vectors=1000000 ms=14148.393 vectors_per_s=70679.41 checksum=0x92cd1159a6bbfc47

compact13:
[VERIFY] vectors=4096 status=pass
[BENCH] model=gsim   vectors=1000000 ms=12371.892 vectors_per_s=80828.38 checksum=0x92cd1159a6bbfc47
[BENCH] model=grhsim vectors=1000000 ms=10845.794 vectors_per_s=92201.64 checksum=0x92cd1159a6bbfc47
```

换算：

```text
old grhsim / gsim wall time      = 14148.393 / 12330.960 = 1.1474x
compact13 grhsim / gsim wall time = 10845.794 / 12371.892 = 0.8766x
compact13 grhsim speedup vs old   = 14148.393 / 10845.794 = 1.3045x
compact13 grhsim throughput / old = 92201.64 / 70679.41 = 1.3045x
```

结论：

- 正确的 compact13 在单 supernode BigComb 上使 grhsim 从比 gsim 慢约 `14.74%`，变成比 gsim 快约 `14.07%`。
- 这说明压缩表达式和局部变量流不仅改善源码/对象体积，也确实改善了优化后二进制的 compute-only 热路径。
- `compact12` 的 mismatch 说明 inline cache 不能简单保存去掉 result type cast 的 raw expression；inline 表达式一旦跨操作组合，C++ usual arithmetic conversion 会改变中间宽度语义，必须保留显式 result-type cast 边界。

## 验证

```text
cmake --build wolvrix/build --target emit-grhsim-cpp
ctest --test-dir wolvrix/build --output-on-failure -R emit-grhsim-cpp
cmake --build wolvrix/build/skbuild --target wolvrix_python
make -C testcase/big-comb/build-one-supernode-compact3/grhsim/model CXX=clang++ CXXFLAGS="-O0 -std=c++20"
make -C testcase/big-comb/build-one-supernode-compact13/grhsim/model CXX=clang++ CXXFLAGS="-O3 -std=c++20"
testcase/big-comb/build-one-supernode-compact13/tb/big_comb_bench --vectors 1000000 --verify 4096
```

`emit-grhsim-cpp` 与 `emit-grhsim-cpp-memory-fill` 均通过。

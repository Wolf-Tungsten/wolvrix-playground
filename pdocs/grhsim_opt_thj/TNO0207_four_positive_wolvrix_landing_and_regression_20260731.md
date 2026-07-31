# TNO0207 Four-positive Wolvrix landing and regression

## 1. 阶段目标与结论

[TNO0205](./TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md) 和
[TNO0206](./TNO0206_simpletes_rwa_to_gen150_endpoint_replication_20260731.md) 将 gen150 的六项变化收敛为
四项正收益子集，并把 residual MemoryRead 与 physical zero-tail 判为中性、不进入默认。本阶段把这四项
精确落入 Wolvrix 生产源码，并将它们作为通用 C++/Python 生成流程的默认行为。

当前结论为 PASS：

- 实际落地后的 grhsim_cpp.cpp 与已测四项 candidate 物化结果逐字节一致；
- 四项均直接位于通用 emitter 默认路径，没有新增 SimTop 条件、命令行 option 或 Python 专用 override；
- 不依赖 active_mask_gap_pack_policy=targeted-direct，也没有改变该开关的默认值或语义；
- targeted、fresh Release/Ninja、fresh full CTest、pybind 与 XS 回归均闭合；
- Wolvrix landing 与 parent executable snapshot 已分别提交。

production control、SimpleTES repin 和最终 RWA→native-four 50k walltime 见
[TNO0208](./TNO0208_four_positive_simpletes_repin_and_native_50k_20260731.md)。

## 2. Patch、文件与提交身份

候选 patch 身份、实际落地文件身份和 Git commit 身份是三类不同对象。本次在真正应用 patch 后重新计算
目标文件哈希，结果如下：

| 对象 | SHA-256 / commit |
| --- | --- |
| 落地前 RWA grhsim_cpp.cpp | 3739547b0c88676a0c0a4ee9c544f60df01754e2d13a18b81e821d11a6c45e84 |
| 已测四项 candidate document | f0a4b4e3ebf7d33b8a32a5dded1298171631da32691805aa48256826698cfceb |
| 已测四项 candidate patch | 6311c22786ebd5a1bc7547cec3e123a8a8d7e9e5e3b8a488ece68d07d4e1dd99 |
| 实际应用后的 grhsim_cpp.cpp | a42690f9f85300a7f8311e07874329a8f02ae0e7aa870af5474e2f3729fdfb82 |
| landing 后 emitter test source | da3137a0562ead93fafb2098b85118bce763b3f90eb2a38094b6eca535f04400 |
| Wolvrix landing commit | fd12d83f5150cc98540ed3e8f2af3b79f8054da0 |
| parent executable snapshot | de37459cdd210794fa5d7423e6f32c145cf71261 |

四项 candidate document/patch 哈希在落地前只说明历史已测输入的身份；它们不表示生产 worktree 已经修改。
实际应用后得到的 a42690f... 才是落地源码身份，并与候选物化结果一致。fd12d83... 是随后实际形成的
Wolvrix commit；de37459... 的 tree 又把 parent 中的 Wolvrix gitlink 固定到该 commit。

Wolvrix commit 只包含两个目标文件：

- lib/emit/grhsim_cpp.cpp；
- tests/emit/test_emit_grhsim_cpp.cpp。

parent snapshot 只更新 Wolvrix gitlink。已有的 Wolvrix .gitignore 修改和
external/mt-kahypar dirty 状态属于用户工作，未被暂存、覆盖或提交。

## 3. 四项通用默认机制

本次落地边界与消融中的四项完全一致：

1. cold SystemTask / assertion hint：SystemTask 的完整执行 guard 走 unlikely；满足无返回值、无输出值等
   约束的 standalone xs_assert_v2 side effect 同样提示为 cold。已有可嵌套 assertion pair 的结构语义不变。
2. selected hot word helpers always-inline：为 trunc/assign/clear/insert/concat/slice 等已测 hot helper 引入
   可移植的 GRHSIM_ALWAYS_INLINE；GCC/Clang 使用 always_inline，其他编译器回退为普通 inline。
3. constant MemoryRead row proof：constLogicIndexValue 能证明常量 row 在真实 rowCount 范围内时，直接发射
   常量下标并标记 alwaysInRange；生成代码不再保留不可能命中的越界清零 pass。
4. dynamic bounds fallback hint：动态 scalar 左/右移的 shift>=64，以及 scalar/word index 的越界或高 word
   非零路径标记为 unlikely；正常值与越界返回语义不变。

明确没有落地的两项是 residual MemoryRead 与 physical zero-tail；它们在 TNO0205/TNO0206 的复测中均未
证明可靠收益。本次也没有借用 targeted-direct 作为四项的总开关。四项不需要 SimTop wrapper 打开，
Python options=None、XS 未设置 override 和普通 C++ 调用都会自然使用相同的 C++ 默认实现。

## 4. Targeted regression

新增或加强的 emitter 覆盖包括：

- 动态 scalar shift 的正常值与越界结果；
- 非 2 的幂 rowCount 下常量 MemoryRead 的 direct load 与越界语义边界；
- SystemTask 和 standalone xs_assert_v2 的 cold hint；
- selected helper 的 always-inline 发射；
- scalar/word index bounds 的 cold fallback；
- assertion outer-guard 测试改为直接检查 DPIC 嵌套结构，不再把 unlikely 当作唯一结构标记。

实际 focused 结果：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| assertion outer-guard | 1/1，8.11 s | PASS |
| exact-event focused | 1/1，18.83 s | PASS |
| deferred focused | 1/1，0.48 s | PASS |
| same-batch focused | 1/1，13.81 s | PASS |
| main emitter target | 1/1，292.62 s | PASS |

## 5. Fresh build 与完整功能回归

从全新目录 build-four-positive-landing-20260731 执行 Release/Ninja，全部 407/407 steps 通过；该计数包含
从头构建的外部依赖。独立 current-source wheel 为：

- 文件：build/wolvrix_four_positive_landing_20260731/wheel/wolvrix-0.1.0-cp312-cp312-linux_x86_64.whl；
- SHA-256：9f0a8bf1069cec46f228cf39fc4ff9dbb1e268a5180830c3c60dab1fe1fd89de。

正式回归结果：

| gate | 绝对结果 | 状态 |
| --- | ---: | --- |
| fresh Release/Ninja | 407/407 steps | PASS |
| fresh full CTest | 50/52，总耗时 287.87 s | PASS，只有两项历史失败 |
| fresh main emitter CTest | 1/1，287.80 s | PASS |
| pybind option tests | 29/29（7+22） | PASS |
| XS sparse-option tests | 32/32，0.041 s | PASS |

full CTest 中唯二未通过项仍是历史已知的 transform-comb-lane-pack 与 transform-repcut；没有新增产品失败。
一次最初的 unittest 调用因模块路径歧义收集到 0 个产品测试，修正为直接执行正式脚本后得到上表
29/29 和 32/32，前者只作为调用方式 discovery，不计入产品回归。

## 6. 阶段裁决

代码身份、默认边界、focused 和 fresh/full 功能回归均闭合，因此四项实现可以进入 production 性能门禁。
本阶段本身不使用历史 gen29 性能代替实际落地后的测量；实际 native 默认生成、功能 canary、正式同 CCD
ABBA+BAAB 和最终 KEEP 裁决独立记录在 TNO0208。

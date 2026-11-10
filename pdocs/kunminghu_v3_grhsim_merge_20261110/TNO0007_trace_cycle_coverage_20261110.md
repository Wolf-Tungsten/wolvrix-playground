# TNO0007 上游 DiffTest trace 覆盖规则适配

## 接口差异

before Gateway 每周期产生 step；after Gateway 的 step 为各 validated bundle valid 的或值。两侧 `trace_write(step)` 都只写入实际 step 数量的 `DiffTestState`，不会补齐无有效事件的周期。因此不能用 `trace records >= guest cycle budget` 判断 after trace 是否完整。

实际生成的记录大小也不同：before 6,216 字节，after 4,672 字节。各自按生成 header 解码、运行完整 NEMU 检查；不把不同 schema 的原始字节当成同一结构比较。格式与生成 RTL 审计见 [difftrace-format-audit.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/difftrace-format-audit.json)。

## 验证器修改

[grhsim_difftrace.py](../../scripts/grhsim_difftrace.py) 和 [grhsim_single_compare.py](../../scripts/grhsim_single_compare.py) 现在要求：

- trace 非空、记录完整、chunk 编号连续；保留 validity-gated 字段比较和 padding 忽略规则。
- architectural cycle 在 chunk 内及 chunk 间单调不减，允许重复 cycle。
- trace 终止 architectural cycle 必须等于对应完整 DiffTest run 日志的 cycleCnt。
- emulator 自身仍须正常达到指定 guest cycle 上限，完整 DiffTest 开启，无错误。
- 复用既有验证时重新检查原始 trace，并核对冻结 binary、header、workload、REF 和运行依赖身份。

该规则接受稀疏有效事件 trace，同时拒绝空 trace、截断、缺块、周期倒退及提前终止。每个版本分别运行 seed 0/1 的 100,000 周期 trace；正式计时关闭 trace。

## focused 验证

`python3 -m unittest discover -s scripts -p 'test_grhsim_single_compare.py' -v`：11 项通过。新增用例验证稀疏记录的终止 cycle、空/失败/未结束检查、同 cycle 合法，以及 chunk 内/跨 chunk 周期倒退拒绝。实际完整双版本 trace 门已启动；结果将在后续功能门记录中追加引用。

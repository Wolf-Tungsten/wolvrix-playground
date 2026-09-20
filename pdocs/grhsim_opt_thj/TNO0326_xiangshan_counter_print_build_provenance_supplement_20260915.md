# TNO0326: XiangShan counter-print build provenance supplement

日期：2026-09-15

状态：`PREBUILD SOURCE SNAPSHOT; POSTBUILD VERIFICATION REQUIRED`。

## 1. 发现与范围

执行 [TNO0325](./TNO0325_xiangshan_counter_print_host_ab_ba_plan_20260915.md) 时，独立审计
确认stage4_build/build_full.py接受新partition package且所有模型空缓存重建，但发现旧工具
的difftest_native_sources扫描不存在的`testcase/xiangshan/difftest/csrc`，实际路径是
`difftest/src/test/csrc`；generated_header_inputs只覆盖头文件，没有两个实际编译的.cpp。
该缺口影响身份记录完整性，不表示模型混用；保留正在运行的builder身份，不原地修改旧工具。

## 2. 独立补充门禁

在两臂都仍处于RepCut/保存JSON、尚未进入native编译时，新增
`build/asc_counter_host_20260915/source_gate.py`：

- `native-source-baseline.json`：实际difftest/src/test/csrc、config和两臂generated-src全文件，117份。
- `verilator-source-baseline.json`：Verilator include/runtime全文件，64份。

实际两臂用于编译的6份helper内容相同；不同的difftest_profile.json仍保留身份。
编译结束后必须用同脚本verify比较完整文件集合与SHA，再写独立verification结果。
若输入变化，不允许进入测量；不能只凭原build-manifest status pass忽略本补充门禁。

完整构建入口13项单测、测量入口35项单测在本轮再次通过。分区/构建主harness为
`build/asc_counter_host_20260915/build_arm.py`；A_v1运行node031，B_v1运行node039，
固定生产库SHA与各自输入GRH SHA，并检查实际映射库路径。

## 3. 测量资源快照

允许13台节点的首轮双NUMA扫描无候选；第二轮发现node030 NUMA1的
`104-111,120-127,136-143,160-167`、monitor0满足3×3秒预扫门槛。
证据为实验根`scans/round01/`、`scans/round02/found.json`及原始CPU/SMT快照。
这只是构建期间的候选，不是预约或正式admission；完成构建后重新扫描，正式每slot仍执行
冻结runner的3×1秒admission。两臂构建不在node030运行，不将构建负载混入Host对照。

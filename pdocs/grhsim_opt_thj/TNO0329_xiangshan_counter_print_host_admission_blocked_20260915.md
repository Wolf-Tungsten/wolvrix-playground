# TNO0329: XiangShan counter-print Host admission blocked

日期：2026-09-15

状态：`RESOURCE BLOCKED BEFORE LAUNCH; NO HOST SAMPLES`。

## 1. 完成与未完成边界

接 [TNO0328构建gate](./TNO0328_xiangshan_counter_print_partition_build_gate_20260915.md)。
A/B全量模型均构建成功，冻结runner的`normalize_arm`对两臂实际执行通过，各11份source
identities；117份native/helper及64份Verilator include在构建前、测量尝试前后SHA均一致。

**本轮C100与C10000均未启动，未得到新的Host时间，也没有runtime功能通过结论。**
不能以编译成功、静态ASC改善、历史Host数据替代本轮AB/BA。

## 2. 资源搜索与两次未launch尝试

资源记录根目录`build/asc_counter_host_20260915/scans/`。round04及round07覆盖
node029–node034、node036–node042全部13节点；round07做两轮。round06复查030/032/039，
round08对030/032做五轮3×3s扫描，均未持续找到可用四CCD。
此前round05瞬时候选见[TNO0327](./TNO0327_xiangshan_counter_print_build_resource_diagnosis_20260915.md)。

固定N=K=32、NUMA0、monitor191、AB先行。两次均使用原runner的4次admission、5秒间隔、
原均值idle≥98%和最低idle≥95%要求，计入计算核及其SMT siblings；没有放宽阈值。

| 尝试 | node030计算CPU | 开始（北京时间） | 结果 |
| --- | --- | --- | --- |
| ab1 / pair1 | `0-7,32-47,72-79` | 13:46:36 | C100/A的4次admission全失败，launch=0 |
| ab2 / pair2 | `0-7,16-23,32-47` | 13:50:28 | C100/A的4次admission全失败，launch=0 |

ab1使用此前round05合格但未预约的mask；ab2改用round08末次NUMA0最接近门槛的四CCD，
该扫描本身仍未合格，仅交给原admission再次判断，未跳过启动gate。

| 尝试/序号 | 整组平均idle% | 最低CPU idle% |
| --- | ---: | ---: |
| ab1/1 | 97.6550 | 0.0000 |
| ab1/2 | 97.2791 | 0.0000 |
| ab1/3 | 97.9791 | 49.8339 |
| ab1/4 | 97.0306 | 47.6821 |
| ab2/1 | 97.9305 | 2.3333 |
| ab2/2 | 97.5991 | 0.0000 |
| ab2/3 | 97.0488 | 0.0000 |
| ab2/4 | 98.0100 | 25.4967 |

ab1首先是CPU72持续满载，ab2是CPU40持续满载；也有其他核/sibling突发负载。
平均空闲度高不表示最慢partition可获得稳定独占算力。

原始记录在`build/repcut_nk32_opt_20260907/runs/`下：

- `counter-print-20260915-node030-ab1/attempts.jsonl`
- `counter-print-20260915-node030-ab2/attempts.jsonl`

每份均保留header、input staging、4次非launch记录。两次runner均因
`admission exhausted before launch`退出，未产生`captured.json`；BA未启动。
没有已启动慢样本被丢弃、重抽或跨mask配对。构建产物和失败记录全部保留。

## 3. 后续启动条件

需要同一NUMA内四个完整CCD，即32个物理核及安静SMT siblings，并有不占目标CCD的monitor。
当前没有独占预约，不沿用昨日node031的预约假设，也未停止/移动其他任务。
找到或预留资源后，可直接使用冻结`spec.json`和两臂ELF，不必重新编译；
用新的output-tag/pair-id完整执行AB→BA，并重新做源码、admission、page与worker gate。
测量尝试后补充源码gate为`native-source-postattempts.json`与
`verilator-source-postattempts.json`，均pass。

本轮在资源阻塞处停止，不后台无限轮询，不将静态结果宣传为Host提速。

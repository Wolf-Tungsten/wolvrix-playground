# NO0569 GrhSIM IR CPU Array Initialization

- 日期：2026-09-07
- 前置：[NO0568](./NO0568_grhsim_ir_cpu_first_commit_20260907.md)
- 范围：补齐 CPU emitter 的逻辑数组初值，保持 DPI compute/可选 event 策略。

## 缺口与实现

此前每个 array InitStep 都生成全数组 memset(0)，既忽略非零值，也把局部覆盖误变成
全量清零。此形态只能证明默认栈能启动，不能作为一般初始化实现。

本阶段实现：

- logic scalar const/random；显式 seed 使用该步骤局部 SplitMix64 状态，缺省 seed
  使用模型共享流。每次 init 重置共享 RNG，宽值逐字直接写入并截断，窄 signed 值归一化。
- array const 要求恰好 count 个 literal 字符串；静态常量表直接 memcpy 到目标。
- array fill 支持 value/random=true 二选一、非负 start/count、count 缺省覆盖剩余行、
  count=0 空操作。零值使用范围 memset；非零值使用静态元素+逐行 memcpy；random
  逐行独立采样，无返回值宽数组和大栈临时值。
- readmem 沿用 legacy 发射期读取文件、嵌入静态地址/数据表的策略；共用从
  `lib/emit/grhsim_cpp.cpp` 提取的注释分词与十六进制地址解析器
  `include/emit/readmem.hpp`。顺序覆盖、绝对 @address、下划线、hex/bin、宽值截断及
  X/Z 的 two-state 投影均保留；短文件/范围外数据不改写其他行。地址溢出和纯下划线
  地址改为明确拒绝，避免绕回合法行。
- 文件内容在预检时缓存，发射期使用同一快照；无效范围、缺失参数、未覆盖初值、
  不支持的初始化类型在输出目录创建前拒绝。real/string state 和嵌套数组仍不支持。

权威 backend 文档补充了文件路径基准、随机策略、参数/操作数边界和小型覆盖示例。
legacy 本体仅替换共用解析函数，未更改调度或初始化发射形式。

## 第一轮验证

经已有根 Makefile 目标 `test_grhsim_cpu_emit`：

- `ptmp/grhsim_cpu_init_test1.log`：退出 0，CTest 19.88 秒。
- 新初始化回归：96 样本、12 次 init，fill 顺序/局部范围、array const、hex/bin sparse
  readmem、重复地址、signed/129-bit 值、逐行 random 和显式 seed 验证通过。
- 18 个非法初值案例拒绝；失败前不写出半成品目录。
- 启动回归改为 16 MiB 数组非零 fill：8 MiB 栈、16 次 init、768 字符串样本通过。
- 既有 DPI/system task 的 384 样本与四组 Verilator 对照继续通过。
- 新运行回归采用 O0 ASan/UBSan。当前环境禁用 LeakSanitizer，不能宣称泄漏扫描通过。

后续补充的 129-bit readmem、分段完整覆盖及 JSON fresh-load 用例正在复验。
共用解析器的 legacy 全量发射回归也在运行。首次 generated Makefile 的 test 调用因
ARGS 中正则末尾 `$` 被 make 展开而没有选中测试，不计入任何通过；已以 `$$` 修正，
并加 `--no-tests=error` 重新执行，日志为 `ptmp/grhsim_legacy_init_test2.log`。

## 后续主目标

新生成目录 gate54 用于验证真实 XiangShan 初值及优化构建，不能复用 gate53 的 O0
对象来声称 O3 性能。10k/50k CoreMark difftest、全量 HDLBits 与 50k 性能门禁仍未完成。

## 增量验证 2026-09-07

- legacy `emit-grhsim-cpp` 全量发射及运行回归退出 0，191.66 秒；日志
  `ptmp/grhsim_legacy_init_test2.log`，详细输出 `ptmp/grhsim_legacy_init_details.log`。
- 扩展用例第二轮遇到测试数据笔误：row7 的 readmem token 多了一个十六进制位，实际
  33 位而参考值按 32 位构造。生成静态数据表正确反映文件，修正为下划线分隔的两个
  64-bit 字；没有因此修改后端。失败日志 `ptmp/grhsim_cpu_init_test2.log` 保留。
- 第三轮通过：`ptmp/grhsim_cpu_init_test3.log`，19.72 秒；完整输出
  `ptmp/grhsim_cpu_init_details3.log`。新增 fixture 经 JSON 写出/重新加载再发射，覆盖
  129-bit readmem 高字、尾字截断、相对路径、分段完整覆盖。96 样本/12 次 init、18 个
  拒绝案例、16 MiB 非零初始化和已有调用测试均通过。
- 四组 Verilator 样本数依次为 4,104（多时钟）、4,196（scalar）、3,072（wide）、
  2,048（wide state），全部通过。
- `make py_install` 退出 0，新实现已安装进项目 `.venv`；日志
  `ptmp/grhsim_cpu_init_install.log`，wheel 临时文件保存在项目 ptmp。
- gate54 完整生成和 fresh-session round-trip 已通过；独立 gate 记录见
  [NO0570](./NO0570_grhsim_ir_cpu_gate54_array_init_20260907.md)。

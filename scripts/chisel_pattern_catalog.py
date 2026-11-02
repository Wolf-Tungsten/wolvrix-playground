"""Open-ended research hypotheses, not a blacklist of Chisel utilities.

Each tuple is: id, Chinese name, lexical symbols, source basename seeds,
mechanism, software alternative, semantic boundary, representative experiments.
Symbols locate evidence; they never establish elaboration or dynamic execution.
"""
from chisel_pattern_findings import review

SPECS = [
('popcount','位计数','PopCount','Bitwise.scala,MSHRCtl.scala','位求和树丢失完整计数语义','打包字 popcount；分散输入单独计入 gather 成本','输入位宽、截断、二态；四态加法不等于 $countones','popcount16,popcount64'),
('count_predicate','计数阈值与基数判断','OnesMoreThan,PopCount','BitUtils.scala,Bitwise.scala','为布尔判断展开完整计数或递归组合','直接基数谓词、位技巧或 popcount 后比较','阈值边界、空输入、重复位、四态未知传播','popcount_threshold,ones_recursive'),
('priority','优先编码与首位查找','PriorityEncoder,ParallelPriorityEncoder','OneHot.scala,ParallelMux.scala','比较／选择网络变成串行位检查','countr_zero/countl_zero 与明确的零输入处理','低位/高位优先、零输入默认值、有效位宽','priority64'),
('onehot','one-hot 编解码','OHToUInt,UIntToOH','OneHot.scala','位归约与解码掩码物化','字级位操作或已证明 one-hot 域内位扫描','多位有效时实际 RTL 的 OR 语义；不能静默改成优先编码','oh_to_uint16'),
('select_n','多个候选选择','SelectFirstN,SelectOne,CircSelectOne,OddEvenSelectOne','BitUtils.scala,Select.scala','反复编码、清位、重建掩码','按有效位迭代并保留每个输出选择','各输出 valid 的门控顺序；未选择时不能提前移除候选','select4'),
('mux_or','并行掩码选择','Mux1H,ParallelMux,ParallelLookUp','Mux.scala,ParallelMux.scala','全宽 mask + OR 访问全部输入','选择位扫描、向量 mask 或经证明的直接索引','零选和多选语义；不能仅凭 Mux1H 名称假设输入互斥','mux1h8'),
('priority_mux','优先多路选择','PriorityMux,ParallelPriorityMux,PriorityMuxDefault','ParallelMux.scala,PriorityMuxDefault.scala','层次结构产生多个临时值或分支','直接索引／短路选择或条件移动','无命中默认值、优先方向、数据读取是否有副作用','priority_mux8'),
('rotate','向量旋转与桶形移位','VecRotate,BarrelShifter,CircularShift,WordShift','VecRotate.scala,BarrelShifter.scala,ShiftUtils.scala','枚举位置和分层 mux 物化','原生 shift/rotate 或按元素重排','向量索引与整数位序不同；非二次幂长度、过大移位、one-hot 状态','rotate8,barrel8'),
('reverse','位反转与字节交换','Reverse','Bitwise.scala','逐位连接在软件端需要 gather；也可能已是 SWAR','编译器 bitreverse/byteswap','bit 与 byte 反转区别；Chisel 已含有仿真优化实现','reverse64'),
('bit_gather','不连续位抽取和掩码扩展','GetEvenBits,GetOddBits,GetRemBits,UIntCompressor,UIntExtractor,MaskExpand','BitUtils.scala,UIntUtils.scala','布线在软件中变成移位与打包','字掩码、分段打包、目标相关位提取','固定/动态掩码、输出顺序、ISA 可用性与指令成本',''),
('wide_concat','宽拼接、切片和物化','Cat,asUInt,asTypeOf','Cat.scala,MaskedDataModule.scala','只需少量结果却物化完整宽值','按需求位生成、延迟索引、跨字切片','共享用户、别名、超宽边界与调试观察；已有 late-index 优化',''),
('prefix','前缀扫描网络','DensePrefixSum,SparsePrefixSum,RipplePrefixSum','PrefixSum.scala','降低电路层数可能增加软件总工作','串行累计、字级并行前缀、SIMD','运算结合性、逐级截断、layerOp 可能插入寄存器','prefix_dense,prefix_ripple'),
('sort','排序与最值网络','HwSort,ParallelMax,ParallelMin,SelectByFn','Sort.scala,ParallelMux.scala,Select.scala','比较交换网络重复移动宽 payload','排序索引、比较后一次搬运或软件小数组算法','稳定性、invalid 元素、环形指针比较；实验仅覆盖无符号有效键','sort4'),
('cam','关联查询与匹配位图','IndexableCAMTemplate','IndexableCAMTemplate.scala','所有表项并行比较展开为大量标量代码','紧凑数组扫描、SIMD 比较或辅助索引','全命中位图、重复键、条目顺序、更新与读的时序；哈希不是默认等价替代','cam8'),
('decode','译码与查表','BitPat,MuxLookup,TruthTable,DecodeLogic,EspressoMinimizer','Lookup.scala,DecodeUnit.scala,CompressUnit.scala','压缩真值表可能展开为布尔网络或比较树','直接 LUT、分级表、switch 或软件规则计算','匹配优先级、dont-care、无匹配默认；表大小与缓存成本','decode_table'),
('csa','进位保存与多操作数求和','CSA,CarrySaveAdder','CSA.scala','显式 sum/carry 网络阻碍原生加法识别','等价模加法或多字累加','进位输出是否被其他用户使用、截断、符号、流水线','csa64'),
('adder','专用加法与比较电路','FastAdderComparator,ParallelSingedExpandingAdd','BitUtils.scala,ParallelMux.scala,VectorIntAdder.scala','进位/传播网络与跨位临时值','原生整数运算、明确扩位的比较','进位输出、signed overflow、饱和、结果宽度；不能把指令级输出当完整组件',''),
('multiply','乘法阵列与压缩树','Multiplier,Booth,Wallace,Compressor','Multiplier.scala,IntMultiplier.scala','部分积及压缩网络展开','原生乘法/多精度乘法并保留流水线状态','有符号高半积、舍入、切片、中间可观察状态与每拍有效信号',''),
('divide','迭代除法与开方','SRT16Divider,Divider,Sqrt','SRT16Divider.scala,Divider.scala','每轮试商、余数和查表','原生运算或精确软件算法加周期状态机','除零、溢出、signed 规则、取消和数据相关延迟',''),
('float','浮点与舍入逻辑','FloatAdder,Rounding,ShiftRightJam,FpFloat','FloatAdder.scala,Rounding.scala,ShiftRightJam.scala','对齐、规格化和分类电路展开','精确浮点软件模型或分步骤整数实现','NaN payload、异常标志、舍入模式、subnormal；host float 不能默认等价',''),
('vector_permute','向量重排、压缩与尾掩码','VCompress,ByteMaskTailGen,MaskExtrator,VecDataSplitModule','VCompress.scala,ByteMaskTailGen.scala,MaskExtrator.scala','多级选择和 lane payload 复制','索引数组、连续块拷贝、位图遍历','元素宽度、vl/vstart、tail/mask policy、跨周期接口',''),
('reg_table','寄存器表动态读写','Reg,VecInit','DataModuleTemplate.scala,BusPerfMonitor.scala,Regfile.scala','索引操作展开成逐项比较和提交','数组索引、共享 enable 与局部变更检测','复位、越界、同周期读写、优先级和 state observation','table16'),
('masked_write','逐字段和逐位写回','MaskData,MaskedDataModule,RegEnable','BitUtils.scala,MaskedDataModule.scala,MSHRBuffer.scala','同一事件和 guard 被重复检查并激活','合并掩码写入与按变化批量激活','重叠写优先级、不同事件、读者集合；不能只按相邻名字合并','masked_write64'),
('sram','SRAM 包装与分 bank 存储','SRAMTemplate,SplittedSRAM,BankedSRAM,SRAMWrapper','SRAMTemplate.scala,SplittedSRAM.scala,BankedSRAM.scala','bank decode、读选和位布局搬移','按 bank/row 访问的软件存储模型','read latency、read-under-write、mask、reset/MBIST、时钟门控',''),
('multiport','多端口与复制存储','RawDataModuleTemplate,SyncDataModuleTemplate,Folded1WDataModuleTemplate','DataModuleTemplate.scala','硬件多端口复制扩大软件访问和提交','共享存储加精确端口事务模型','同地址多写冲突、读旧/新值、各端口时钟、原有确定性',''),
('queue','队列与多入多出缓冲','Queue,MIMOQueue,MultiPortQueue,ShiftQueue,OverrideableQueue','Queue.scala,MIMOQueue.scala,MultiPortQueue.scala','数据移位、指针译码和逐槽提交','环形缓冲与周期级握手模型','flow/pipe、flush、满空边界、同时入出队、内部观察；实验覆盖 Queue 的一个配置','queue8'),
('pipeline','流水线与握手传播','Pipeline,PipeWithFlush,PipelineConnect,RegNextN,LatencyPipe','Pipeline.scala,PipeWithFlush.scala,PipelineConnect.scala','逐级复制、valid/ready 扇出和重复激活','紧凑流水状态数组与精确逐拍转移','停顿、flush、旁路、保持值和每一级可观察状态',''),
('arbitration','仲裁器与公平性状态','RRArbiter,FastArbiter,BinaryArbiterNode,OldestFirstArbiter','FastArbiter.scala,Arbiter.scala,BinaryArbiterNode.scala','树状仲裁与持有/轮转状态','位图选择加仲裁状态模型','锁定、背压、grant/ready 关系、轮转更新条件、公平性',''),
('freelist','空闲项分配与回收','FreeList,StdFreeList,MEFreeList','FreeList.scala,StdFreeList.scala,MEFreeList.scala','前缀偏移、多个优先选择和位图更新组合','位图扫描或环形数组，多请求事务更新','分配顺序、checkpoint、回滚、重复释放、同周期回收/分配',''),
('age','年龄矩阵与最老项选择','AgeDetector,NewAgeDetector','AgeDetector.scala,NewAgeDetector.scala','矩阵逐 bit 更新与每行归约','紧凑位图行更新；另行研究状态表示变换','同拍多入队优先级、无效条目、reset；时间戳替代需要回绕和可观察性证明','age8'),
('replacement','替换策略与 LRU 状态','ReplacementPolicy,PseudoLRU,PLRU,RandomReplacement','Replacement.scala,Replacer.scala','树节点/矩阵的选择、更新和展开','压缩状态字与位操作','策略、touch 次序、无效 way、多个访问、随机序列一致',''),
('lfsr','伪随机与反馈状态','LFSR64,LFSR,PRNG,GaloisLFSR','LFSR64.scala,LFSR.scala,GaloisLFSR.scala','反馈与逐位移位可能已被编译器化简','原生移位/xor 状态更新','tap、初值、零状态修正、enable、序列与周期完全相同','lfsr64'),
('crc','CRC 线性变换','CRC','CRC.scala','每个输出 bit 的 parity cone；存在共享','字级矩阵 parity、查表或匹配多项式的指令','多项式、bit order、反射、初末异或；CRC 指令不通用','crc16'),
('ecc','ECC 与 syndrome','SECCode,SECDEDCode,ParityCode','ECC.scala','多 parity 与 syndrome 选择','字掩码 parity、固定映射与软件纠错','poison、错误分类、数据/校验位置、双错误等；实验先覆盖 encode','ecc32,parity64'),
('xor_fold','散列与折叠归约','XORFold,ParallelXOR','BitUtils.scala,ParallelMux.scala','切片、拼接和逐层归约','字级 xor/shift；可能已经完全优化','最后不足一组的补零、结果位宽、共享用户','xor_fold'),
('counter','性能与饱和计数器','XSPerfAccumulate,SaturateCounter,Counter,GTimer','PerfCounterUtils.scala,SaturateCounter.scala,Counter.scala','大量独立 enable/reset 比较和 commit','保持精确状态的批量计数更新','溢出、清零、打印时机、disable 保持；不能删除统计功能',''),
('histogram','直方图与滚动统计','XSPerfHistogram,XSPerfRolling,TransactionLatencyCounter','PerfCounterUtils.scala,HardwarePerfMonitor.scala','每个桶的范围检查和状态更新','直接桶索引、共享范围计算或紧凑数组','边界桶、累计周期、窗口重置、总计与打印输出',''),
('logging','日志、trace 和 DPI','LogPerfEndpoint,ChiselDB,ChiselTaggedTrace,CLog','LogUtils.scala,ChiselDB.scala,ChiselTaggedTrace.scala','条件与参数打包、外部调用、日志汇聚','延迟参数计算、批量打包、明确的外部模型接口','有副作用、调用次数与顺序、启用条件；日志模块名不等于运行时 printf',''),
('clock_gate','门控时钟与事件逻辑','ClockGate,ClockGatedReg,ClockMux','ClockGate.scala,ClockGatedReg.scala,ClockMux.scala','额外事件域和变化检测；省硬件功耗未必省调度','明确门控事件/enable 语义并复用事件计算','latch 透明相位、门控 glitch、异步变化；不能直接把 clock 改成 enable',''),
('reset','复位分发与初始化','ResetCatchAndSync,AsyncResetReg,RegInit','ResetCatchAndSync.scala,AsyncResetReg.scala','大扇出 reset、逐项初始化与保持逻辑','共享事件检测、类型明确的批量初始化','同步/异步、极性、释放同步、初值与未初始化数据',''),
('fsm','状态编码与协议控制','ChiselEnum,Enum,Switch','Enum.scala,Switch.scala,MSHR.scala','one-hot/译码状态在软件中较宽且分支多','明确状态机转移或有限域查表','非法状态、reset、输出组合依赖、时序和状态映射',''),
('dup_share','复制逻辑与共享锥','Duplicate,dontTouch,BoringUtils','Duplicate.scala,BoringUtils.scala','硬件复制改善扇出，但仿真可能重复算；共享又可能增通信','按仿真分区和活动依赖选择共享/局部复制','跨分区传输、计算时机、波形可观察性、增量失效关系',''),
('broadcast','宽广播与读者激活','Fill,VecInit','Bitwise.scala,RegisterSlice.scala','宽 mask 物化和大规模 dirty/active 写入','保留广播语义、共享触发、按变化更新','各读者依赖、布局、并发同步；不能只看静态 fanout 判成本',''),
('commit','大规模提交与固定点传播','RegEnable,RegNext','Reg.scala,LogUtils.scala,MSHR.scala','小状态写入聚合成巨型函数，调用后再次传播','同 guard/同读者分组、精确变化检测与局部模型','状态优先级、事件、读者集合、固定点收敛；batch345 整体计时不能按行分配',''),
('observability','调试观测与汇聚结构','DifftestModule,dontTouch,GatewayEndpoint','GatewayEndpoint.scala,LogUtils.scala','内部信号保留、宽打包和延迟链增加仿真工作','保留观测契约的紧凑快照与按需打包','Difftest 顺序、每拍信号、波形和调试能力；不能把删除观测算等价优化',''),
('host_only','仅 elaboration 执行的工具','log2Ceil,Parameters,ChiselAnnotation,SourceInfo','Math.scala,Generator.scala,CustomAnnotations.scala','编译时间与仿真运行时间容易混淆','分别统计 elaboration/build 成本与生成电路成本','Scala 循环本身不是每拍循环；需要追踪其生成结果',''),
]

# Additions from the second source-review pass (not constrained by the seed list).
SPECS += [
('gray_decode','Gray 编码的前缀 xor','GrayToBinary,BinaryToGray','GrayCode.scala','逐 bit scanLeft 保留串行 xor 与打包','对完整字做 log2(width) 次 xor-shift','宽度、位序、二态；切勿把跨拍 Gray 同步器当纯组合替代','gray_decode32'),
('self_compare_gate','自比较生成的寄存器 enable','GatedRegNext,GatedRegEnable,GatedValidRegNext','ClockGatedReg.scala','硬件避免无变化写入，仿真可能再次比较新旧值','与普通 RegNext 同语义对照后决定是否消除重复检测','相位、复位、输入保持和激活依赖；不能直接认定有重复成本','gated_reg64,plain_reg64'),
('guarded_compute','guard 后的昂贵纯计算','Mux,when','PerfCounterUtils.scala,SRT16Divider.scala','昂贵分支可能提前计算，也可能已被后端按需求值','条件计算、共享结果与精确失效条件','guard、异常/副作用、除零、四态；实测普通 if 未必优于生成表达式','guarded_div32'),
('register_map','寄存器映射与延迟写入','RegMap,MaskedRegMap,ConditionalRegMap','RegMap.scala','地址译码与逐寄存器更新；某些包装主动延迟一拍以降低扇出','表驱动地址映射及明确的延迟写事务','MaskedRegMap 源码有 RegNext；写函数、mask、优先级不能被直接数组赋值抹去',''),
('fp_recode','浮点重编码与分类','RecFNToIN,INToRecFN,recFNFromFN,rawFloatFromRecFN','RecFNToIN.scala,INToRecFN.scala,recFNFromFN.scala','表示转换、规格化和分类布尔网络','精确位级软件转换；可独立于整个浮点执行单元','recode 位格式、NaN、例外标志、非规格化数和舍入',''),
]

EXTRA_BENCHES = {
    'popcount':['popcount32'], 'count_predicate':['ones_recursive16'], 'priority':['priority16'],
    'mux_or':['mux1h4'], 'decode':['decode16'], 'crc':['crc16_table'], 'sort':['sort4_network'],
    'reg_table':['table64','table64_indexed'], 'cam':['cam8_state'], 'queue':['queue8_flow'],
    'bit_gather':['bit_extract64','bit_deposit16'], 'histogram':['histogram8'],
}

STRUCTURAL_CASES = {
    'cam8':'IndexableCAMTemplate 的组合全匹配读锥；输入来自打包数据，未包含存储更新',
    'sort4':'无符号有效键的 4 元素比较交换网络；不是 HwSort 的完整 valid/环形指针契约',
    'sort4_network':'与 sort4 相同网络，软件候选也使用固定网络',
    'csa64':'显式三操作数 carry-save 加最终求和；输出只观察模 2^64 的和',
    'table16':'Reg(Vec) 结构缩小实例；16×32-bit，额外观察所有表项的 xor',
    'table64':'Reg(Vec) 结构缩小实例；64×32-bit，额外观察所有表项的 xor',
    'table64_indexed':'64×32-bit Reg(Vec)，只观察动态读端口，用于检查额外观测的影响',
    'masked_write64':'8 字节 enable 写入锥；不包含其他模块的多写端口',
    'age8':'8×8 单入队矩阵的明确缩小实例；不是多端口 AgeDetector 的完整替代',
    'histogram8':'XSPerfHistogram 的桶更新锥：[8,40)、step=4、两端裁剪；不含日志与 mean 统计',
    'guarded_div32':'32-bit 无符号除法的组合 guard；显式将除数最低位置 1',
    'wire64':'直接连接校准；不作为待优化 utility',
    'native_add64':'原生三操作数加法校准；不作为待优化 utility',
}


def catalog():
    result=[]
    for row in SPECS:
        ident,title,symbols,files,mechanism,alternative,boundary,bench=row
        result.append(dict(id=ident,title=title,symbols=symbols.split(','),source_seeds=files.split(','),
            suspected_cost=mechanism,software_alternative=alternative,semantic_boundary=boundary,
            benchmark_cases=(bench.split(',') if bench else [])+EXTRA_BENCHES.get(ident,[]),
            **review(ident)))
    return result

优化grhsim-ir路线的单线程仿真 xiangshan coremark 50k 性能，参照物gsim仿真时间~40s， 同时要求编译时间 <30min 。
鼓励的优化手段：扩展grhsim-ir语义支持，提供更多高性能的op及emit方法，改善分区调度算法，实现行为等价但性能更优的子图替换等 。
禁止的优化手段：修改已冻结的grh ir及grh上的pass，修改xiangshan以及测试相关源码，采用多线程加速，生成针对特定模块名称匹配的优化算法 。
每个方向在完成任务时要报告优化后 xiangshan coremark 50k 的实测单线程性能，注意，测试性能需要wolvrix-playground复杂的构建环境（build目录），请充分复用，不要尝试自己搭建。

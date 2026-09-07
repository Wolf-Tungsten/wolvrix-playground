# NO0556 GrhSIM IR CPU array init compile Gate

从项目内 `ptmp/grhsim_gate33.log` 提取到首条稳定错误：数组 state 初始化将 scalar literal 通过 `normalize()` 强转为嵌套 `std::array`。已在 emitter 入口对数组初始化生成合法 `{}` aggregate，先闭合 C++ 类型与布局；逐元素 literal/readmem/random 初始化语义仍待实现。

# NO0553 GrhSIM IR CPU nested concat Gate

Gate 26 的 XiangShan 实际编译已进入嵌套宽 concat，发现 `concat_words` 的 lhs 模板参数错误使用累计逻辑宽度，而嵌套表达式实际始终采用结果 words 容器。已修正 lhs 参数为当前结果 word 数，保持生成类型与 legacy words helper 一致；待重新执行集成编译确认。

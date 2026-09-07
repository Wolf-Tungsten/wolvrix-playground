# NO0554 GrhSIM IR CPU string escape Gate

Gate 27 已进入全量 task 编译并越过 concat 类型错误；发现 `core.compute.constant` 的 string 参数可能包含换行和引号，导致生成 C++ 字面量语法错误。已加入反斜杠、引号、换行、回车、制表符转义，并通过 `make py_install` 刷新 binding。集成编译待重新验证。

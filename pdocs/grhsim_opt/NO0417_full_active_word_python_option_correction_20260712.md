# NO0417 Full active-word Python option correction

日期：2026-07-12

## 1. Failed preflight

按 [NO0416](./NO0416_full_active_word_consume_fresh_emit_plan_20260712.md) 首次启动 SimTop fresh emit。
pre-reg checkpoint 读取、reg-to-mem 和 activity schedule 均完成，结构计数也复现预期；但在调用
C++ emitter 前，Python wrapper 拒绝新增关键字：

```text
TypeError: emit_grhsim_cpp got unexpected named parameters: full_active_word_consume
```

失败日志为：

```text
build/logs/xs/xs_wolf_grhsim_emit_no0416_full_word_consume_20260712.log
elapsed=337.39 user=307.42 sys=29.66 maxrss=29132392
```

该次执行没有进入 C++ emit，因而没有可用于结构、编译、功能或性能结论的 generated C++。问题不是
schedule 或 emitter 语义失败，而是 `Session.emit_grhsim_cpp` 的 Python 参数白名单遗漏。

## 2. Correction

nested `wolvrix` commit `17291fe` 在 Python API 中：

1. 显式公开 `full_active_word_consume: bool | None`；
2. 将非 `None` 值传入 native emitter；
3. 在 `_compile_emit_grhsim_cpp_kwargs` 中允许该关键字并严格要求 `bool`。

所有命令均先执行 `source env.sh`。源码 `py_compile` 通过，随后执行：

```text
python3 -m pip install --no-build-isolation -e wolvrix
```

editable wheel 构建和安装成功。实际导入文件与源码 SHA256 均为：

```text
8c1a3085d6295e9c7db39f99aeb6a167af8a8ff019fcc9c2ecb2c0471234b0dc
```

从 `.venv/lib/python3.12/site-packages/wolvrix/__init__.py` 直接调用 validator，`True/False` 均通过，
整数 `1` 按预期抛出 `ValueError`；实际 `Session.emit_grhsim_cpp` signature 也包含该参数。

## 3. Next gate

复用 NO0416 已声明的 checkpoint、output 和结构门禁，从头重跑 fresh emit。只有新日志 exit 0、明确记录
`full_active_word_consume=True`，且 full/partial/commit source parser 全部通过，才进入 O3 build。

# NO0418 Full active-word native binding correction

日期：2026-07-12

## 1. Second failed preflight

[NO0417](./NO0417_full_active_word_python_option_correction_20260712.md) 修正 Python wrapper 后，第二次启动
NO0416 fresh emit。reg-to-mem 与 activity schedule 均成功，schedule stats SHA256 已复现：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

但 native extension 的 `session_emit_grhsim_cpp` 签名仍未包含该关键字，因而在 C++ emitter 前失败：

```text
TypeError: 'full_active_word_consume' is an invalid keyword argument for this function
elapsed=340.23 user=311.42 sys=28.76 maxrss=29130164
```

修正后日志为：

```text
build/logs/xs/xs_wolf_grhsim_emit_no0416_full_word_consume_corrected_20260712.log
```

该次同样没有 generated C++，不能用于后续结构、编译、功能或性能结论。它同时证明 graph/schedule
结构 gate 已通过，但不证明 emitter option 生效。

## 2. Native correction

nested `wolvrix` commit `e76aa0f` 在 native pybind 层补齐：

1. `PyArg_ParseTupleAndKeywords` 的参数对象、format string 和 keyword list；
2. bool truth-value 解析；
3. `EmitOptions.attributes["full_active_word_consume"]` 传递；
4. native method docstring signature。

重新执行 editable install 后，实际加载的 extension 为：

```text
_wolvrix.so SHA256:       b5f0f212e5a6dd29e44ff121fcd862185ab190b66ef8f2bdefc112b3ffa4d4e9
libwolvrix-lib.so SHA256: a10f39f90f53686739ebff4c112bcc5e7b62f3a380bc9c9b906ff50c77b4504a
```

`_wolvrix.so` strings 同时包含 option 名和更新后的完整 native signature。

## 3. End-to-end smoke

使用 `testcase/hdlbits/dut/dut_001.v` 运行实际 Python 链路：读 SV、标准 transforms、activity schedule，
最后调用：

```text
Session.emit_grhsim_cpp(..., full_active_word_consume=True)
```

执行 exit 0，并生成 9 个 `.cpp`。该 smoke 已实际穿过 wrapper、native binding 和 C++ emitter，不再只做
关键字 validator 检查。full-word 语义与 source shape 仍由 NO0415 的 9 级链 C++ test 覆盖。

## 4. Next gate

第三次 NO0416 SimTop fresh emit 仍使用原 output/config。只有 emitter 成功、direct-read summary 命中且
full/partial/commit source parser 通过，才接受 fresh source，并另起 O3 build gate。

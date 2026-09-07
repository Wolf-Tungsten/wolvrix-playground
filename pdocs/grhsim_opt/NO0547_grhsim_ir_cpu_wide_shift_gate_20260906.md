# NO0547 GrhSIM IR CPU wide shift gate

日期：2026-09-06

Make gate 17 越过宽 `sliceArray`，首个失败为 128 位 `core.compute.shl`。emitter 已按 legacy
pointer/out-buffer API 接入 `shl/lshr/ashr`，直接写结果 value slot；通过项目 `make py_install`
刷新 binding。后续仍需宽 add/sub/mul、比较、reduce、动态 slice 和完整 runtime ABI。

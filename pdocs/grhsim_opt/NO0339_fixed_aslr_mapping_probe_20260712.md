# NO0339 Fixed-ASLR mapping probe

日期：2026-07-12

## 1. 口径

按 [NO0338](./NO0338_pie_aslr_performance_runbook_correction_20260712.md)，连续两次用以下 prefix 启动同一个
numeric NO0300 10k 仿真：

```text
setarch "$(uname -m)" -R numactl --membind=1 taskset -c 138
```

进程运行期间读取 `/proc/<pid>/maps`，只保留指向 emu 文件的 mappings；仿真结束后同时检查功能终点。

## 2. Mapping 结果

两次均得到完全相同的 5 段映射：

```text
555555554000-55555555c000 r--p 00000000 .../emu
55555555c000-55555a977000 r-xp 00008000 .../emu
55555a977000-55555af8e000 r--p 05423000 .../emu
55555af8e000-55555af90000 r--p 05a3a000 .../emu
55555af90000-55555af91000 rw-p 05a3c000 .../emu
```

两个 map 文件 SHA256 均为：

```text
ebd497697d53d94d8394f161568019c8c30e43cd9426f7314ce58e627b53416f
```

这证明 `ADDR_NO_RANDOMIZE` 已传递到实际 emu，executable text base 固定为 `0x55555555c000`，不是只对
shell probe 生效。

## 3. 功能与下一步

两次都得到 guest cycles `10001`、`cycleCnt = 9996`、`instrCnt = 458` 和 terminal PC `0x800027c6`，
无 mismatch/assertion/error。Host time 为 `10,079/10,071 ms`，只用于确认 probe 稳定，不作正式性能数据。

mapping gate 通过。NO0334 的 numeric/bit-reversal/numeric 三轮从头重跑，所有命令都使用同一 fixed-ASLR
prefix；NO0338 标记无效的旧 numeric1 不混入统计。

## 4. 产物

```text
build/logs/xs_perf/no0334/fixed_aslr_map_probe1.maps
build/logs/xs_perf/no0334/fixed_aslr_map_probe1_emu.log
build/logs/xs_perf/no0334/fixed_aslr_map_probe2.maps
build/logs/xs_perf/no0334/fixed_aslr_map_probe2_emu.log
```

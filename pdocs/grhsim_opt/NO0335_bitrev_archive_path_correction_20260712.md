# NO0335 Bit-reversal archive path correction

日期：2026-07-12

## 1. 失败现象

执行 [NO0334](./NO0334_no0300_sched_object_order_plan_20260712.md) 的首次 archive 构造时，命令先切换到
实验 `grhsim_emit` 目录，再用相对路径读取原 NO0300 archive 和写入日志。两个路径都多使用了一层 `..`：

```text
ar: .../libgrhsim_SimTop.a: No such file or directory
tee: .../bitrev_archive_members.txt: No such file or directory
```

该命令没有运行链接或仿真。原 NO0300 archive/emu 未修改；实验副本中的原 archive/emu hardlink 已先安全
unlink，但随后只临时生成了包含 117 个 sched members、缺少 state/eval/state-init 的无效 archive。

## 2. 修正

重建实验 archive 时改用仓库内绝对路径，不再从切换后的工作目录推导层级；构造完成后增加以下硬门禁：

```text
non-sched members = 35
sched members = 117
total members = 152
```

并检查 non-sched 顺序与原 archive 一致、sched 顺序与预声明 7-bit bit-reversal 列表一致。任一计数或顺序
不符时不得进入 emu 链接。

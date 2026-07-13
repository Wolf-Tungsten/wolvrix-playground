# NO0369 readelf section-alignment parser correction

日期：2026-07-12

## 1. 失败现象

NO0368 direct aligned model 完成编译后，首次批量检查 117 个 sched objects 的 `.text` section alignment，verifier
错误报告：

```text
sched_objects=117 bad_alignment=117 bad_compiler=0
```

该结果与同一批产物中 `grhsim_SimTop_sched_33.o` 的直接输出矛盾，后者明确显示 `.text` alignment 为 4096：

```text
[ 2] .text PROGBITS ... 4096
```

因此首次 `bad_alignment=117` 是 verifier false negative，不是编译失败；该结果不进入 build gate，也没有运行仿真。

## 2. 根因与修正

首次 AWK 假设 section name 位于 `$2`：

```awk
$2 == ".text" { print $NF }
```

`readelf -SW` 会把带空格的 section index `[ 2]` 拆为 `$1="["` 和 `$2="2]"`，所以 `.text` 实际位于
`$3`。旧 verifier 没有匹配任何行，空字符串随后被计为 bad alignment。

修正为：

```awk
$3 == ".text" { print $NF; exit }
```

## 3. 重跑结果

对同一批、未修改的 117 个 sched objects 全量重跑：

```text
sched_objects=117 bad_alignment=0 bad_compiler=0
```

所有 objects 的 `.text` alignment 都是 4096，`.comment` 都包含 Clang 21.1.5。该修正只改变检查命令，未修改
generated source、object、archive 或 emu，也未触发重编。NO0368 build/layout gate 可以继续。

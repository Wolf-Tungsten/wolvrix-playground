# TNO0130 NUMA first-touch and tmpfs page-cache root cause

记录日期：2026-07-18

状态：补充解释前面 stage7+ 等实验中 NUMA0/NUMA1 数据方向差异的根因，并固化后续 staging/运行命令。NUMA 节点本身的 CPU、内存控制器和 `numactl` 绑定语法没有被证明不对；主要错误是把“新 inode”误当成“页面已经在目标 NUMA”，而没有约束创建/首次写入 tmpfs 文件的 CPU 和内存节点。

## 1. 现象证据

Stage26 min1000 首次 N1 ABBA 的 control 运行由 runner 正确拒绝：

```text
Host time spent: 73561ms
placement.tsv:
  emu  0 21260
  nemu 110 5
placement_ok=0
```

这里的列是 `N0/N1` 页计数。emu 的页面基本在 N1，但 `nemu.so` 的 115 页只有 5 页在 N1，绝大多数在 N0；因此这个样本不能用于 N1 walltime。进程 `/proc/<pid>/status` 中的 `Mems_allowed_list: 0-1` 也没有否定该事实：allowed mask 只表示允许分配的节点，不表示已经驻留的页；判据必须是 `/proc/<pid>/numa_maps` 的实际页计数。

随后在全新目录中，以 N1 CPU171 执行复制动作本身的绑定：

```bash
taskset -c 171 numactl --physcpubind=171 --membind=1 \
  cp --reflink=never source-file /dev/shm/.../n1/file
```

四个文件（control/candidate/image/reference）均如此创建，新 inode 为 `5463/5464/5465/5466`，SHA 与源文件一致。之后 N1 ABBA/BAAB 的每个有效样本均为：emu `0/21260`、candidate NEMU `0/115`，`placement_ok=1`，migration=0。min10000 staging 从创建开始对 N0 CPU43/`membind=0` 和 N1 CPU139/`membind=1` 逐文件复制，也得到 NEMU N0/N1 `0/115`。

## 2. 为什么只绑运行进程不够

`/dev/shm` 是 tmpfs。文件第一次被 `cp` 写入时，数据页由执行 `cp` 的 CPU/NUMA 节点分配；对同一 inode 的后续 `exec`、`dlopen` 或 `mmap` 会复用这些 file-backed page-cache 页。运行时命令：

```bash
taskset -c 139 numactl --physcpubind=139 --membind=1 \
  perf stat -- setarch x86_64 -R emu -i coremark.bin --diff nemu.so -C 50000
```

在语法上是正确的，能限制 emu 的 CPU 和新分配；但它不会自动把已经在 N0 page cache 中的 `nemu.so` 页迁移到 N1。可执行文件的私有 text 页常在进程 fault 时重新生成/复制，因而可能看起来本地；共享的 NEMU file-backed 页则直接暴露 first-touch 节点差异。这正好解释了“emu 本地、nemu 远端”的拒绝样本。

因此，`inode` 独立只解决了不同候选之间不共享缓存的问题，不能解决 inode 内部页的 NUMA 首触；复制命令的 first-touch 绑定和运行前 `numa_maps` 验证都是必要条件。这个原因与 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 记录的 NFS/file-backed locality 问题相互印证，但本次是 tmpfs page-cache 的具体扩展。

## 3. 固化的正确协议

1. 每个 NUMA 节点使用全新 `/dev/shm` 目录和独立 inode；不在已有文件上覆盖。
2. 对 binary、image、reference 每一个文件，在目标节点执行 `taskset -c <copy-cpu> numactl --physcpubind=<copy-cpu> --membind=<node> cp --reflink=never`。
3. 记录 `stat` inode/size/mode 与 SHA；不能只记录路径。
4. formal runner 运行前检查 `numa_maps`：emu 在目标节点至少 `99.9%`，NEMU 至少 `95%`；失败样本保留证据但不进入均值。
5. 运行使用 `taskset -c <target-cpu> numactl --physcpubind=<target-cpu> --membind=<node> perf stat -- setarch x86_64 -R ...`，并同时通过整 node 前置/运行期 idle gate、五项 PMU scheduled、migration=0、功能终点和唯一 walltime 检查。

这套流程已经用于 TNO0129 的 min1000/min10000；后续 stage7+ 重测不得再使用仅由 unbound `cp` 创建的 N1 staging，也不得以 `Mems_allowed_list` 代替 `numa_maps` placement。

## 4. 对历史 NUMA 差异的结论边界

此前不同 stage 的 N0/N1 方向反转不能直接解释为 schedule 在两个对称 socket 上真实收益相反；至少有一部分样本混入了 file-page first-touch/page-cache 差异。修正 staging 后，仍可能有正常的 node 空闲程度、代码布局和 cache 状态波动，所以最终必须报告每个节点的绝对 walltime、idle/placement 证据和 ABBA/BAAB 重复，而不能用单次 cycles 比值推断 socket 对称性或非对称性。

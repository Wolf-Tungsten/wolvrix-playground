# NO0331 Batch function page-alignment build gate

日期：2026-07-12

## 1. 构建口径

按 [NO0329](./NO0329_batch_function_page_alignment_plan_20260712.md) 复用 NO0286/NO0300 generated C++，
并应用 [NO0330](./NO0330_direct_model_build_compiler_correction_20260712.md) 的 direct-build 修正：

```text
CXX=clang++ AR=ar ARFLAGS=rv
CXXFLAGS=-std=c++20 -O3 -falign-functions=4096
```

两边各使用 16 个编译槽，总并发 32；构建前 load 约 `5.62/384`，可用内存约 945 GiB。构建中 load
上升到约 34，与主动并发吻合，未出现额外资源争用。

155 个 generated `.cpp/.hpp/Makefile` 在构建后仍与各自原始目录共享 inode，内容未修改。两边都生成
117 个 sched objects 和完整 archive，随后使用独立 difftest `BUILD_DIR` 链接 emu。

## 2. 编译与布局验证

代表性 sched object 的 `.comment` 为 Clang 21.1.5，主 `.text` section alignment 为 4096。最终 emu 中：

| Model | Batch symbols | Non-page-aligned | Distinct low-12-bit offsets before | After |
| --- | ---: | ---: | ---: | ---: |
| NO0286 aligned | 117 | 0 | 93 | 1 |
| NO0300 aligned | 117 | 0 | 100 | 1 |

逐符号比较确认，两边 117 个 batch 的 symbol size 均与各自未对齐原版完全相同。因此 compiler 没有改变
batch body 或内部指令规模，本轮二进制差异来自函数前 padding 和地址变化。

## 3. 体积

| Model | Original `.text` | Aligned `.text` | Delta |
| --- | ---: | ---: | ---: |
| NO0286 | 97,049,715 | 98,681,395 | +1,631,680 (+1.68%) |
| NO0300 | 88,185,721 | 89,843,625 | +1,657,904 (+1.88%) |

两个版本的绝对 padding 增量只差 26,224 bytes。虽然相对增幅不同，old/new 都承受约 1.6 MiB padding，
可以进入配对诊断；该体积增长仍不应视为可保留优化。

aligned emu SHA256：

```text
NO0286 46c2c5df8e15a11ba807a68c59e80495cd84cf069613c746576460c2eaa6952a
NO0300 bf48702e77ed8b5ecd4c5c1728e713676521eaa84257801b5a3df03709d76df0
```

## 4. 产物与下一步

```text
build/xs_grhsim_no0329_no0286_align4k_20260712/grhsim/grhsim-compile/emu
build/xs_grhsim_no0329_no0300_align4k_20260712/grhsim/grhsim-compile/emu
build/logs/xs_perf/no0329/no0286_align4k_model_build_clang.log
build/logs/xs_perf/no0329/no0300_align4k_model_build_clang.log
build/logs/xs_perf/no0329/no0286_align4k_emu_link.log
build/logs/xs_perf/no0329/no0300_align4k_emu_link.log
```

本篇只验收 build/layout，尚未运行模拟。下一步先做 aligned old/new 10k 与 50k 功能门禁，再进入 fixed-CPU
PMU A/B/A。

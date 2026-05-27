# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  # grh-ir-visualize

  一个独立的 Web 工具，用来导入 wolvrix `store_json(...)` 导出的完整 GRH Design JSON，并以 graph 为粒度浏览层次结构与图内原理图式布局。

  ## 设计目标

  - 输入是层次化 GRH JSON，不是 harness 的 compute-op-dag。
  - 左侧同时给出 top graph / instance tree 与 graph 列表。
  - 主画布使用 worker + canvas，而不是 DOM/SVG 节点洪泛。
  - 大图支持分级渲染：缩小时显示层间 bundle，放大后再切到单边绘制。

  ## 本地启动

  ```bash
  cd grh-ir-visualize
  npm install
  npm run dev
  ```

  构建检查：

  ```bash
  cd grh-ir-visualize
  npm run build
  ```

  ## 输入 JSON 约定

  导入文件应为 wolvrix StoreJson 输出，顶层至少包含：

  - `graphs`
  - `tops`
  - 每个 graph 的 `vals` / `ports` / `ops`

  viewer 会读取：

  - `kInstance` / `kBlackbox` 的 `attrs.moduleName` 与 `attrs.instanceName` 来构建层次树
  - `vals[].def` 与 `ops[].in/out` 来恢复 graph 内数据流

  ## 生成完整 Xiangshan 层次化 JSON

  仓库里不一定已经有可直接导入的完整 Xiangshan JSON。推荐直接复用 Makefile 里的 Xiangshan 生成链：

  ```bash
  make xs_wolf_hier_json
  ```

  它会沿用 `xs_wolf_emit` 的 filelist 与 read-args 组织方式，但调用一个不做 `hier-flatten` 的导出脚本，输出路径默认是：

  ```bash
  build/xs/wolf/wolf_emit/xs_wolf_hier.json
  ```

  如果你要手工调用底层脚本，命令是：

  ```bash
  python grh-ir-visualize/tools/export_xiangshan_hier_json.py <filelist> <top> <json_out> <read_args_file> --roundtrip
  ```

  脚本特性：

  - 读取 Xiangshan SV 设计
  - 参考 `xs_wolf_emit` 的前半段 pass 链，但不执行 `hier-flatten`
  - 导出 `store_json`
  - 可选做一次 `read_json_file` roundtrip 验证

  ## 当前实现边界

  - graph 内布局采用稳定的拓扑分层近似，而不是完整 EDA 级正交布线器。
  - 对超大 graph，缩放较低时只绘制 layer bundle；这是为完整 Xiangshan 规模保留交互流畅性。
  - 如果某些层次关系没有 `kInstance` 保留下来，viewer 仍可按 graph symbol 浏览，但实例树会退化。

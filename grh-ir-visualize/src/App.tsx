import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import GraphCanvas from './components/GraphCanvas'
import type {
  DesignOverview,
  GraphDetail,
  GraphSummary,
  HierarchyNode,
  WorkerRequest,
  WorkerResponse,
} from './lib/grh'
import './App.css'

const workerUrl = new URL('./workers/grhWorker.ts', import.meta.url)

function formatCount(value: number): string {
  return new Intl.NumberFormat('en-US').format(value)
}

function metric(label: string, value: number | string) {
  return (
    <div className="metric-card" key={label}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  )
}

type TreeItemProps = {
  node: HierarchyNode
  selectedPath: string | null
  onSelect: (node: HierarchyNode) => void
  depth?: number
}

function TreeItem({
  node,
  selectedPath,
  onSelect,
  depth = 0,
}: TreeItemProps) {
  const hasChildren = node.children.length > 0
  const [expanded, setExpanded] = useState(depth < 1)
  const isSelected = selectedPath === node.path

  return (
    <div className="tree-item">
      <div
        className={`tree-row ${isSelected ? 'is-selected' : ''}`}
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        <button
          type="button"
          className="tree-toggle"
          onClick={() => setExpanded((value) => !value)}
          disabled={!hasChildren}
          aria-label={hasChildren ? (expanded ? 'collapse' : 'expand') : 'leaf'}
        >
          {hasChildren ? (expanded ? '−' : '+') : '•'}
        </button>
        <button
          type="button"
          className="tree-select"
          onClick={() => onSelect(node)}
        >
          <span className="tree-label">{node.instanceName ?? node.label}</span>
          <span className="tree-module">{node.graphSymbol}</span>
        </button>
      </div>
      {expanded && hasChildren ? (
        <div className="tree-children">
          {node.children.map((child) => (
            <TreeItem
              key={child.id}
              node={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function App() {
  const workerRef = useRef<Worker | null>(null)
  const latestDesignRequest = useRef(0)
  const latestGraphRequest = useRef(0)
  const [fileName, setFileName] = useState<string>('')
  const [overview, setOverview] = useState<DesignOverview | null>(null)
  const [graph, setGraph] = useState<GraphDetail | null>(null)
  const [selectedGraph, setSelectedGraph] = useState<string | null>(null)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [searchText, setSearchText] = useState('')
  const [isLoadingDesign, setIsLoadingDesign] = useState(false)
  const [isLoadingGraph, setIsLoadingGraph] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [fitSignal, setFitSignal] = useState(0)

  useEffect(() => {
    const worker = new Worker(workerUrl, { type: 'module' })
    workerRef.current = worker

    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const message = event.data
      if (message.type === 'design-loaded') {
        if (message.requestId !== latestDesignRequest.current) {
          return
        }
        setOverview(message.design)
        setFileName(message.fileName)
        setIsLoadingDesign(false)
        setErrorText(null)
        const initialGraph =
          message.design.tops[0] ?? message.design.graphs[0]?.symbol ?? null
        setSelectedNodeId(null)
        startTransition(() => {
          setSelectedGraph(initialGraph)
          setSelectedPath(initialGraph)
        })
        return
      }
      if (message.type === 'graph-loaded') {
        if (message.requestId !== latestGraphRequest.current) {
          return
        }
        setGraph(message.graph)
        setSelectedNodeId(null)
        setIsLoadingGraph(false)
        setErrorText(null)
        setFitSignal((value) => value + 1)
        return
      }
      if (message.type === 'error') {
        setErrorText(message.message)
        if (message.stage === 'load-design') {
          setIsLoadingDesign(false)
          setOverview(null)
          setGraph(null)
        } else {
          setIsLoadingGraph(false)
        }
      }
    }

    return () => {
      worker.terminate()
      workerRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!workerRef.current || !overview || !selectedGraph) {
      return
    }
    const requestId = latestGraphRequest.current + 1
    latestGraphRequest.current = requestId
    setIsLoadingGraph(true)
    const request: WorkerRequest = {
      type: 'load-graph',
      requestId,
      symbol: selectedGraph,
      instancePath: selectedPath ?? undefined,
    }
    workerRef.current.postMessage(request)
  }, [overview, selectedGraph, selectedPath])

  const deferredSearch = useDeferredValue(searchText.trim().toLowerCase())

  const filteredGraphs = useMemo(() => {
    const items = overview?.graphs ?? []
    if (!deferredSearch) {
      return items
    }
    return items.filter((item) => {
      const haystack = `${item.symbol} ${item.topKinds.join(' ')} ${item.children.join(' ')}`
      return haystack.toLowerCase().includes(deferredSearch)
    })
  }, [deferredSearch, overview?.graphs])

  const selectedNode = useMemo(() => {
    if (!graph || !selectedNodeId) {
      return null
    }
    return graph.nodes.find((node) => node.id === selectedNodeId) ?? null
  }, [graph, selectedNodeId])

  async function onFilePicked(file: File | undefined) {
    if (!file || !workerRef.current) {
      return
    }
    const requestId = latestDesignRequest.current + 1
    latestDesignRequest.current = requestId
    setOverview(null)
    setGraph(null)
    setFileName(file.name)
    setSelectedGraph(null)
    setSelectedPath(null)
    setSelectedNodeId(null)
    setErrorText(null)
    setIsLoadingDesign(true)
    setIsLoadingGraph(false)
    const buffer = await file.arrayBuffer()
    const request: WorkerRequest = {
      type: 'load-design',
      requestId,
      fileName: file.name,
      buffer,
    }
    workerRef.current.postMessage(request, [buffer])
  }

  function selectGraph(summary: GraphSummary) {
    startTransition(() => {
      setSelectedGraph(summary.symbol)
      setSelectedPath(summary.symbol)
      setSelectedNodeId(null)
    })
  }

  function selectHierarchyNode(node: HierarchyNode) {
    startTransition(() => {
      setSelectedGraph(node.graphSymbol)
      setSelectedPath(node.path)
      setSelectedNodeId(null)
    })
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Wolvrix GRH JSON Viewer</p>
          <h1>grh-ir-visualize</h1>
          <p className="lead">
            以 graph 为粒度浏览层次化 GRH IR，使用 worker 解析和 canvas 分层绘制，
            针对完整 Xiangshan 规模做了缩放分级渲染。
          </p>
        </div>
        <label className="import-button">
          <input
            type="file"
            accept="application/json,.json"
            onChange={(event) => {
              void onFilePicked(event.target.files?.[0])
              event.currentTarget.value = ''
            }}
          />
          <span>{isLoadingDesign ? 'Parsing JSON…' : 'Open GRH JSON'}</span>
        </label>
      </header>

      {overview ? (
        <section className="metrics-grid">
          {metric('File', fileName)}
          {metric('Graphs', formatCount(overview.summary.graphCount))}
          {metric('Operations', formatCount(overview.summary.operationCount))}
          {metric('Values', formatCount(overview.summary.valueCount))}
          {metric('Hierarchy calls', formatCount(overview.summary.instanceCount))}
          {metric('Top graphs', overview.tops.join(', ') || 'n/a')}
        </section>
      ) : (
        <section className="empty-hero">
          <div>
            <h2>导入层次化 GRH JSON</h2>
            <p>
              期望输入是 wolvrix store_json 导出的 Design JSON，包含 graphs、tops 和每个
              graph 的 vals、ports、ops。不要使用 hier-flatten 之后的单图结果。
            </p>
          </div>
          <pre className="hero-snippet">python tools/export_xiangshan_hier_json.py ... --roundtrip</pre>
        </section>
      )}

      {errorText ? <div className="error-banner">{errorText}</div> : null}

      <main className="workspace-layout">
        <aside className="panel sidebar-panel">
          <div className="panel-section">
            <div className="section-head">
              <h2>Hierarchy</h2>
              <span>{overview ? formatCount(overview.tree.length) : '0'} roots</span>
            </div>
            <div className="hierarchy-tree">
              {overview ? (
                overview.tree.map((node) => (
                  <TreeItem
                    key={node.id}
                    node={node}
                    selectedPath={selectedPath}
                    onSelect={selectHierarchyNode}
                  />
                ))
              ) : (
                <p className="placeholder">导入 JSON 后显示 top graph 与实例树。</p>
              )}
            </div>
          </div>

          <div className="panel-section grow">
            <div className="section-head">
              <h2>Graphs</h2>
              <span>{formatCount(filteredGraphs.length)}</span>
            </div>
            <label className="search-box">
              <span>Filter</span>
              <input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="symbol, op kind, child module"
              />
            </label>
            <div className="graph-list">
              {filteredGraphs.map((item) => (
                <button
                  type="button"
                  key={item.symbol}
                  className={`graph-list-item ${selectedGraph === item.symbol ? 'is-active' : ''}`}
                  onClick={() => selectGraph(item)}
                >
                  <strong>{item.symbol}</strong>
                  <span>
                    {formatCount(item.opCount)} ops · {formatCount(item.valueCount)} vals ·{' '}
                    {formatCount(item.instanceCount)} inst
                  </span>
                  <small>{item.topKinds.join(' · ') || 'no ops'}</small>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <section className="panel canvas-panel">
          <div className="canvas-toolbar">
            <div>
              <p className="eyebrow">Graph View</p>
              <h2>{graph?.symbol ?? selectedGraph ?? 'No graph selected'}</h2>
              <p className="subtle">
                {graph
                  ? `${formatCount(graph.nodes.length)} nodes · ${formatCount(graph.edges.length)} edges · ${formatCount(graph.layerCount)} layers`
                  : '选择 graph 或实例路径后显示结构图。'}
              </p>
            </div>
            <div className="toolbar-actions">
              <button type="button" onClick={() => setFitSignal((value) => value + 1)}>
                Fit to view
              </button>
              <div className="loading-pill">{isLoadingGraph ? 'Building layout…' : 'Ready'}</div>
            </div>
          </div>
          <GraphCanvas
            graph={graph}
            fitSignal={fitSignal}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
        </section>

        <aside className="panel inspector-panel">
          <div className="panel-section">
            <div className="section-head">
              <h2>Graph summary</h2>
            </div>
            {graph ? (
              <dl className="summary-list">
                <div>
                  <dt>Symbol</dt>
                  <dd>{graph.symbol}</dd>
                </div>
                <div>
                  <dt>Instance path</dt>
                  <dd>{graph.instancePath ?? graph.symbol}</dd>
                </div>
                <div>
                  <dt>Operations</dt>
                  <dd>{formatCount(graph.opCount)}</dd>
                </div>
                <div>
                  <dt>Values</dt>
                  <dd>{formatCount(graph.valueCount)}</dd>
                </div>
                <div>
                  <dt>Ports</dt>
                  <dd>{formatCount(graph.portCount)}</dd>
                </div>
                <div>
                  <dt>Backedges</dt>
                  <dd>{formatCount(graph.backedgeCount)}</dd>
                </div>
              </dl>
            ) : (
              <p className="placeholder">等待 graph 数据。</p>
            )}
          </div>

          <div className="panel-section grow">
            <div className="section-head">
              <h2>Node inspector</h2>
            </div>
            {selectedNode ? (
              <div className="node-card">
                <div className="node-heading">
                  <strong>{selectedNode.label}</strong>
                  <span>{selectedNode.kind}</span>
                </div>
                <p className="node-role">{selectedNode.role}</p>
                {selectedNode.secondaryLabel ? (
                  <p className="node-secondary">{selectedNode.secondaryLabel}</p>
                ) : null}
                <div className="token-row">
                  {selectedNode.inputs.length > 0 ? (
                    <span>{selectedNode.inputs.length} inputs</span>
                  ) : null}
                  {selectedNode.outputs.length > 0 ? (
                    <span>{selectedNode.outputs.length} outputs</span>
                  ) : null}
                  <span>Layer {selectedNode.layer}</span>
                </div>
                {selectedNode.attrs.length > 0 ? (
                  <div className="detail-block">
                    <h3>Attributes</h3>
                    <ul className="detail-list">
                      {selectedNode.attrs.map(([key, value]) => (
                        <li key={key}>
                          <strong>{key}</strong>
                          <span>{value}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {selectedNode.inputs.length > 0 ? (
                  <div className="detail-block">
                    <h3>Inputs</h3>
                    <ul className="detail-list compact-list">
                      {selectedNode.inputs.map((name) => (
                        <li key={name}>{name}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {selectedNode.outputs.length > 0 ? (
                  <div className="detail-block">
                    <h3>Outputs</h3>
                    <ul className="detail-list compact-list">
                      {selectedNode.outputs.map((name) => (
                        <li key={name}>{name}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="placeholder">点击图中的 op 或端口查看细节。</p>
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App

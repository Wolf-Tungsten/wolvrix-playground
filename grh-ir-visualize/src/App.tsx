import {
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import GraphCanvas from './components/GraphCanvas'
import type {
  DesignOverview,
  GraphDetail,
  HierarchyNode,
  WorkerRequest,
  WorkerResponse,
} from './lib/grh'
import './App.css'

const workerUrl = new URL('./workers/grhWorker.ts', import.meta.url)

function formatCount(value: number): string {
  return new Intl.NumberFormat('en-US').format(value)
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

function metric(label: string, value: number | string) {
  return (
    <div className="metric-card" key={label}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  )
}

type OverlayPanelProps = {
  title: string
  caption?: string
  collapsed: boolean
  onToggle: () => void
  children: ReactNode
}

function OverlayPanel({
  title,
  caption,
  collapsed,
  onToggle,
  children,
}: OverlayPanelProps) {
  return (
    <section className={`overlay-panel ${collapsed ? 'is-collapsed' : ''}`}>
      <button type="button" className="overlay-panel-toggle" onClick={onToggle}>
        <span className="overlay-panel-heading">
          <strong>{title}</strong>
          {caption ? <small>{caption}</small> : null}
        </span>
        <span className="overlay-panel-icon" aria-hidden="true">
          {collapsed ? '+' : '−'}
        </span>
      </button>
      {!collapsed ? <div className="overlay-panel-body">{children}</div> : null}
    </section>
  )
}

type TreeItemProps = {
  node: HierarchyNode
  selectedPath: string | null
  onSelect: (node: HierarchyNode) => void
  onExpand: (node: HierarchyNode) => void
  pendingPaths: Set<string>
  depth?: number
}

function updateTreeChildren(
  nodes: HierarchyNode[],
  path: string,
  children: HierarchyNode[],
): HierarchyNode[] {
  let changed = false
  const nextNodes = nodes.map((node) => {
    if (node.path === path) {
      changed = true
      return { ...node, children, childrenLoaded: true }
    }
    if (!path.startsWith(`${node.path}/`) || node.children.length === 0) {
      return node
    }
    const nextChildren = updateTreeChildren(node.children, path, children)
    if (nextChildren === node.children) {
      return node
    }
    changed = true
    return { ...node, children: nextChildren }
  })
  return changed ? nextNodes : nodes
}

function findHierarchyNodeByPath(nodes: HierarchyNode[], path: string): HierarchyNode | null {
  for (const node of nodes) {
    if (node.path === path) {
      return node
    }
    if (path.startsWith(`${node.path}/`) && node.children.length > 0) {
      const childMatch = findHierarchyNodeByPath(node.children, path)
      if (childMatch) {
        return childMatch
      }
    }
  }
  return null
}

function TreeItem({
  node,
  selectedPath,
  onSelect,
  onExpand,
  pendingPaths,
  depth = 0,
}: TreeItemProps) {
  const hasChildren = node.childCount > 0
  const [expanded, setExpanded] = useState(depth < 1)
  const isSelected = selectedPath === node.path
  const containsSelectedDescendant = selectedPath
    ? selectedPath !== node.path && selectedPath.startsWith(`${node.path}/`)
    : false
  const isLoadingChildren = pendingPaths.has(node.path)

  useEffect(() => {
    if (containsSelectedDescendant) {
      setExpanded(true)
    }
  }, [containsSelectedDescendant])

  useEffect(() => {
    if (expanded && hasChildren && !node.childrenLoaded && !isLoadingChildren) {
      onExpand(node)
    }
  }, [expanded, hasChildren, isLoadingChildren, node, onExpand])

  return (
    <div className="tree-item">
      <div
        className={`tree-row ${isSelected ? 'is-selected' : ''}`}
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        <button
          type="button"
          className="tree-toggle"
          onClick={() => {
            if (!expanded && hasChildren && !node.childrenLoaded && !isLoadingChildren) {
              onExpand(node)
            }
            setExpanded((value) => !value)
          }}
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
          {node.childrenLoaded ? (
            node.children.map((child) => (
              <TreeItem
                key={child.id}
                node={child}
                selectedPath={selectedPath}
                onSelect={onSelect}
                onExpand={onExpand}
                pendingPaths={pendingPaths}
                depth={depth + 1}
              />
            ))
          ) : (
            <p className="placeholder">Loading hierarchy…</p>
          )}
        </div>
      ) : null}
    </div>
  )
}

function App() {
  const workerRef = useRef<Worker | null>(null)
  const latestDesignRequest = useRef(0)
  const latestHierarchyRequest = useRef(0)
  const latestGraphRequest = useRef(0)
  const hierarchyRequestPathById = useRef(new Map<number, string>())
  const [fileName, setFileName] = useState<string>('')
  const [overview, setOverview] = useState<DesignOverview | null>(null)
  const [graph, setGraph] = useState<GraphDetail | null>(null)
  const [selectedGraph, setSelectedGraph] = useState<string | null>(null)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [isLoadingDesign, setIsLoadingDesign] = useState(false)
  const [isLoadingGraph, setIsLoadingGraph] = useState(false)
  const [designLoadProgress, setDesignLoadProgress] = useState<{ phase: string; progress: number } | null>(null)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [pendingHierarchyPaths, setPendingHierarchyPaths] = useState<Set<string>>(new Set())
  const [fitSignal, setFitSignal] = useState(0)
  const [isDesignPanelCollapsed, setIsDesignPanelCollapsed] = useState(false)
  const [isHierarchyPanelCollapsed, setIsHierarchyPanelCollapsed] = useState(false)
  const [isInspectorPanelCollapsed, setIsInspectorPanelCollapsed] = useState(false)
  const pendingHierarchyPathsRef = useRef(new Set<string>())

  function setHierarchyPathPending(path: string, pending: boolean) {
    const next = new Set(pendingHierarchyPathsRef.current)
    if (pending) {
      next.add(path)
    } else {
      next.delete(path)
    }
    pendingHierarchyPathsRef.current = next
    setPendingHierarchyPaths(next)
  }

  useEffect(() => {
    const worker = new Worker(workerUrl, { type: 'module' })
    workerRef.current = worker

    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const message = event.data
      if (message.type === 'design-progress') {
        if (message.requestId !== latestDesignRequest.current) {
          return
        }
        setDesignLoadProgress({ phase: message.phase, progress: message.progress })
        return
      }
      if (message.type === 'design-loaded') {
        if (message.requestId !== latestDesignRequest.current) {
          return
        }
        setOverview(message.design)
        pendingHierarchyPathsRef.current = new Set()
        setPendingHierarchyPaths(new Set())
        hierarchyRequestPathById.current.clear()
        setFileName(message.fileName)
        setIsLoadingDesign(false)
        setDesignLoadProgress(null)
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
      if (message.type === 'hierarchy-children-loaded') {
        hierarchyRequestPathById.current.delete(message.requestId)
        setHierarchyPathPending(message.path, false)
        setOverview((current) => {
          if (!current) {
            return current
          }
          return {
            ...current,
            tree: updateTreeChildren(current.tree, message.path, message.children),
          }
        })
        setErrorText(null)
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
          setDesignLoadProgress(null)
          setOverview(null)
          setGraph(null)
        } else if (message.stage === 'load-hierarchy-children') {
          const path = hierarchyRequestPathById.current.get(message.requestId)
          if (path) {
            hierarchyRequestPathById.current.delete(message.requestId)
            setHierarchyPathPending(path, false)
          }
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

  const selectedNode = useMemo(() => {
    if (!graph || !selectedNodeId) {
      return null
    }
    return graph.nodes.find((node) => node.id === selectedNodeId) ?? null
  }, [graph, selectedNodeId])

  const selectedValue = useMemo(() => {
    if (!graph || !selectedNodeId) {
      return null
    }
    return graph.values.find((value) => value.id === selectedNodeId) ?? null
  }, [graph, selectedNodeId])

  const hasInspectorSelection = selectedNode !== null || selectedValue !== null
  const selectedNodeSymbol = useMemo(() => {
    if (!selectedNode || selectedNode.role !== 'op') {
      return null
    }
    const candidates = [selectedNode.navigationSymbol, selectedNode.secondaryLabel].filter(
      (value): value is string => Boolean(value),
    )
    return candidates.find((value) => value !== selectedNode.kind && value !== selectedNode.label) ?? null
  }, [selectedNode])

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
    setDesignLoadProgress({ phase: 'Opening JSON', progress: 0 })
    pendingHierarchyPathsRef.current = new Set()
    setPendingHierarchyPaths(new Set())
    hierarchyRequestPathById.current.clear()
    const request: WorkerRequest = {
      type: 'load-design',
      requestId,
      fileName: file.name,
      file,
    }
    workerRef.current.postMessage(request)
  }

  function selectHierarchyNode(node: HierarchyNode) {
    startTransition(() => {
      setSelectedGraph(node.graphSymbol)
      setSelectedPath(node.path)
      setSelectedNodeId(null)
    })
  }

  function openNodeFromCanvas(nodeId: string) {
    const node = graph?.nodes.find((candidate) => candidate.id === nodeId)
    if (!node?.navigationPath || !node.navigationSymbol) {
      return
    }
    startTransition(() => {
      setSelectedGraph(node.navigationSymbol)
      setSelectedPath(node.navigationPath)
      setSelectedNodeId(null)
    })
  }

  const currentPath = graph?.instancePath ?? selectedPath
  const parentPath = currentPath && currentPath.includes('/') ? currentPath.slice(0, currentPath.lastIndexOf('/')) : null

  function goToParentHierarchy() {
    if (!overview || !parentPath) {
      return
    }
    const parentNode = findHierarchyNodeByPath(overview.tree, parentPath)
    if (!parentNode) {
      return
    }
    startTransition(() => {
      setSelectedGraph(parentNode.graphSymbol)
      setSelectedPath(parentNode.path)
      setSelectedNodeId(null)
    })
  }

  function loadHierarchyChildren(node: HierarchyNode) {
    if (!workerRef.current || node.childrenLoaded || node.childCount === 0) {
      return
    }
    if (pendingHierarchyPathsRef.current.has(node.path)) {
      return
    }
    const requestId = latestHierarchyRequest.current + 1
    latestHierarchyRequest.current = requestId
    hierarchyRequestPathById.current.set(requestId, node.path)
    setHierarchyPathPending(node.path, true)
    const request: WorkerRequest = {
      type: 'load-hierarchy-children',
      requestId,
      symbol: node.graphSymbol,
      path: node.path,
    }
    workerRef.current.postMessage(request)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar-dock">
        <section className="overlay-brand-card">
          <div>
            <h1>Wolvrix GRH IR Viewer</h1>
          </div>
          <div className="overlay-actions">
            <label className="import-button">
              <input
                type="file"
                accept="application/json,.json"
                onChange={(event) => {
                  void onFilePicked(event.target.files?.[0])
                  event.currentTarget.value = ''
                }}
              />
              <span>{isLoadingDesign ? 'Opening GRH JSON…' : 'Open GRH JSON'}</span>
            </label>
          </div>
          {isLoadingDesign && designLoadProgress ? (
            <div className="design-load-progress" aria-live="polite">
              <div className="design-load-progress-header">
                <span>{designLoadProgress.phase}</span>
                <strong>{formatPercent(designLoadProgress.progress)}</strong>
              </div>
              <div className="design-load-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(designLoadProgress.progress * 100)}>
                <div
                  className="design-load-progress-fill"
                  style={{ width: `${Math.max(6, Math.round(designLoadProgress.progress * 100))}%` }}
                />
              </div>
            </div>
          ) : isLoadingGraph ? (
            <div className="loading-pill">Building layout…</div>
          ) : null}
          {errorText ? <div className="error-banner floating-banner">{errorText}</div> : null}
        </section>

        <OverlayPanel
          title="Current Graph"
          caption={graph?.symbol ?? selectedGraph ?? (overview ? fileName : 'No graph loaded')}
          collapsed={isDesignPanelCollapsed}
          onToggle={() => setIsDesignPanelCollapsed((value) => !value)}
        >
          {graph ? (
            <div className="panel-copy design-panel-copy">
              <div className="current-graph-path-card">
                <span className="current-graph-path-label">Path</span>
                <strong className="current-graph-path-value">{graph.instancePath ?? graph.symbol}</strong>
              </div>
              <section className="metrics-grid floating-metrics">
                {metric('Operations', formatCount(graph.opCount))}
                {metric('Values', formatCount(graph.valueCount))}
              </section>
            </div>
          ) : (
            <div className="panel-copy design-panel-copy">
              <p className="placeholder">Open a GRH JSON file and choose a hierarchy path to inspect the current graph.</p>
              <pre className="hero-snippet">python tools/export_xiangshan_hier_json.py ... --roundtrip</pre>
            </div>
          )}
        </OverlayPanel>

        <OverlayPanel
          title="Hierarchy"
          caption={`${overview ? formatCount(overview.tree.length) : '0'} roots`}
          collapsed={isHierarchyPanelCollapsed}
          onToggle={() => setIsHierarchyPanelCollapsed((value) => !value)}
        >
          <div className="hierarchy-tree overlay-scroll-panel">
            {overview ? (
              overview.tree.map((node) => (
                <TreeItem
                  key={node.id}
                  node={node}
                  selectedPath={selectedPath}
                  onSelect={selectHierarchyNode}
                  onExpand={loadHierarchyChildren}
                  pendingPaths={pendingHierarchyPaths}
                />
              ))
            ) : (
              <p className="placeholder">导入 JSON 后显示实例层次。</p>
            )}
          </div>
        </OverlayPanel>

        {hasInspectorSelection ? (
          <OverlayPanel
            title="Inspector"
            collapsed={isInspectorPanelCollapsed}
            onToggle={() => setIsInspectorPanelCollapsed((value) => !value)}
          >
            <div className="overlay-scroll-panel inspector-panel-body">
              <div className="detail-block">
              {selectedNode ? (
                <div className="node-card">
                  <div className="node-heading">
                    <strong>{selectedNode.role === 'op' ? 'Op' : 'Port'}</strong>
                  </div>
                  <dl className="summary-list selection-summary-list">
                    <div>
                      <dt>Type</dt>
                      <dd>{selectedNode.kind}</dd>
                    </div>
                    {selectedNodeSymbol ? (
                      <div>
                        <dt>Symbol</dt>
                        <dd>{selectedNodeSymbol}</dd>
                      </div>
                    ) : null}
                    <div>
                      <dt>Name</dt>
                      <dd>{selectedNode.label}</dd>
                    </div>
                    {selectedNode.secondaryLabel && selectedNode.secondaryLabel !== selectedNodeSymbol ? (
                      <div>
                        <dt>Detail</dt>
                        <dd>{selectedNode.secondaryLabel}</dd>
                      </div>
                    ) : null}
                  </dl>
                  <div className="token-row">
                    {selectedNode.inputs.length > 0 ? (
                      <span>{selectedNode.inputs.length} inputs</span>
                    ) : null}
                    {selectedNode.outputs.length > 0 ? (
                      <span>{selectedNode.outputs.length} outputs</span>
                    ) : null}
                    <span>Layer {selectedNode.layer.toFixed(2)}</span>
                  </div>
                  {selectedNode.attrs.length > 0 ? (
                    <div className="detail-block nested-detail-block">
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
                    <div className="detail-block nested-detail-block">
                      <h3>Inputs</h3>
                      <ul className="detail-list compact-list">
                        {selectedNode.inputs.map((name) => (
                          <li key={name}>{name}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {selectedNode.outputs.length > 0 ? (
                    <div className="detail-block nested-detail-block">
                      <h3>Outputs</h3>
                      <ul className="detail-list compact-list">
                        {selectedNode.outputs.map((name) => (
                          <li key={name}>{name}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : selectedValue ? (
                <div className="node-card">
                  <div className="node-heading">
                    <strong>Value</strong>
                  </div>
                  <dl className="summary-list selection-summary-list">
                    <div>
                      <dt>Name</dt>
                      <dd>{selectedValue.label}</dd>
                    </div>
                    {selectedValue.secondaryLabel ? (
                      <div>
                        <dt>Detail</dt>
                        <dd>{selectedValue.secondaryLabel}</dd>
                      </div>
                    ) : null}
                  </dl>
                  {selectedValue.attrs.length > 0 ? (
                    <div className="detail-block nested-detail-block">
                      <h3>Attributes</h3>
                      <ul className="detail-list">
                        {selectedValue.attrs.map(([key, value]) => (
                          <li key={key}>
                            <strong>{key}</strong>
                            <span>{value}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <div className="detail-block nested-detail-block">
                    <h3>Source</h3>
                    <ul className="detail-list compact-list">
                      <li>{selectedValue.sourceId ?? 'n/a'}</li>
                    </ul>
                  </div>
                  {selectedValue.targetIds.length > 0 ? (
                    <div className="detail-block nested-detail-block">
                      <h3>Targets</h3>
                      <ul className="detail-list compact-list">
                        {selectedValue.targetIds.map((targetId) => (
                          <li key={targetId}>{targetId}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="placeholder">No selection.</p>
              )}
            </div>
            </div>
          </OverlayPanel>
        ) : null}
      </aside>

      <main className="canvas-shell">
        <div className="canvas-stage">
          <GraphCanvas
            graph={graph}
            fitSignal={fitSignal}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onOpenNode={openNodeFromCanvas}
            onFitView={() => setFitSignal((value) => value + 1)}
            onGoUpOneLevel={goToParentHierarchy}
            canGoUpOneLevel={Boolean(parentPath)}
          />
          <div className="canvas-stage-scrim" />
        </div>
      </main>
    </div>
  )
}

export default App

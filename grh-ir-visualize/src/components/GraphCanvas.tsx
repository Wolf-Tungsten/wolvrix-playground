import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from 'react'
import type { GraphDetail, SchematicEdge, SchematicNode, SchematicValue } from '../lib/grh'

type Camera = {
  x: number
  y: number
  scale: number
}

type Viewport = {
  width: number
  height: number
}

type DragState = {
  pointerId: number
  lastX: number
  lastY: number
  moved: boolean
}

type GraphCanvasProps = {
  graph: GraphDetail | null
  fitSignal: number
  selectedNodeId: string | null
  onSelectNode: (nodeId: string | null) => void
  onOpenNode?: (nodeId: string) => void
  onFitView?: () => void
  onGoUpOneLevel?: () => void
  canGoUpOneLevel?: boolean
}

type RenderNode = SchematicNode & {
  originalIds: string[]
  syntheticGroup: 'inputs' | 'outputs' | null
}

type RenderEdge = SchematicEdge & {
  sourceId: string
  targetId: string
  sourceNodeIds: string[]
  targetNodeIds: string[]
  aggregatedValueIds: string[]
}

type RenderGraph = {
  nodes: RenderNode[]
  edges: RenderEdge[]
}

type EdgePoint = {
  x: number
  y: number
}

type EdgeRoute = {
  x1: number
  y1: number
  x2: number
  y2: number
  x3: number
  y3: number
  x4: number
  y4: number
  midpoint: EdgePoint
  bounds: {
    left: number
    right: number
    top: number
    bottom: number
  }
}

type PortExpansionState = {
  inputsExpanded: boolean
  outputsExpanded: boolean
}

const MIN_SCALE = 0.03
const MAX_SCALE = 2.5
const MAX_CANVAS_DIMENSION = 8192
const MAX_CANVAS_PIXELS = 16_777_216

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function zoomOutFactor(scale: number): number {
  return clamp((0.9 - scale) / 0.87, 0, 1)
}

function hexToRgb(hex: string) {
  const normalized = hex.replace('#', '')
  const value = normalized.length === 3
    ? normalized
        .split('')
        .map((char) => `${char}${char}`)
        .join('')
    : normalized
  const parsed = Number.parseInt(value, 16)
  return {
    r: (parsed >> 16) & 255,
    g: (parsed >> 8) & 255,
    b: parsed & 255,
  }
}

function mixHex(left: string, right: string, amount: number): string {
  const t = clamp(amount, 0, 1)
  const a = hexToRgb(left)
  const b = hexToRgb(right)
  const r = Math.round(a.r + (b.r - a.r) * t)
  const g = Math.round(a.g + (b.g - a.g) * t)
  const bChannel = Math.round(a.b + (b.b - a.b) * t)
  return `rgb(${r}, ${g}, ${bChannel})`
}

function rgbaHex(hex: string, alpha: number): string {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1)})`
}

function computeBackingStore(viewport: Viewport, devicePixelRatio: number) {
  const cssWidth = Math.max(1, viewport.width)
  const cssHeight = Math.max(1, viewport.height)
  const basePixelWidth = Math.max(1, Math.floor(cssWidth * devicePixelRatio))
  const basePixelHeight = Math.max(1, Math.floor(cssHeight * devicePixelRatio))

  let scaleFactor = 1
  if (basePixelWidth > MAX_CANVAS_DIMENSION || basePixelHeight > MAX_CANVAS_DIMENSION) {
    scaleFactor = Math.min(
      scaleFactor,
      MAX_CANVAS_DIMENSION / basePixelWidth,
      MAX_CANVAS_DIMENSION / basePixelHeight,
    )
  }

  const pixelCount = basePixelWidth * basePixelHeight
  if (pixelCount > MAX_CANVAS_PIXELS) {
    scaleFactor = Math.min(scaleFactor, Math.sqrt(MAX_CANVAS_PIXELS / pixelCount))
  }

  const pixelWidth = Math.max(1, Math.floor(basePixelWidth * scaleFactor))
  const pixelHeight = Math.max(1, Math.floor(basePixelHeight * scaleFactor))

  return {
    pixelWidth,
    pixelHeight,
    renderScale: devicePixelRatio * scaleFactor,
  }
}

function fitGraphToNodes(
  nodes: SchematicNode[],
  edges: SchematicEdge[],
  edgeRoutes: Map<string, EdgeRoute>,
  viewport: Viewport,
): Camera {
  const primaryOps = nodes.filter(
    (node) =>
      node.role === 'op' &&
      node.kind !== 'kRegisterReadPort' &&
      node.kind !== 'kLatchReadPort' &&
      node.kind !== 'kRegisterWritePort' &&
      node.kind !== 'kLatchWritePort',
  )
  const fallbackOps = nodes.filter((node) => node.role === 'op')
  const sourceNodes = primaryOps.length > 0 ? primaryOps : fallbackOps.length > 0 ? fallbackOps : nodes
  const horizontalMargin = 40
  const topMargin = 84
  const bottomMargin = 40
  const usableWidth = Math.max(viewport.width - horizontalMargin * 2, 200)
  const usableHeight = Math.max(viewport.height - topMargin - bottomMargin, 160)
  let left = Math.min(...sourceNodes.map((node) => node.x))
  let top = Math.min(...sourceNodes.map((node) => node.y))
  let right = Math.max(...sourceNodes.map((node) => node.x + node.width))
  let bottom = Math.max(...sourceNodes.map((node) => node.y + node.height))

  for (const edge of edges) {
    if (edge.kind !== 'backedge') {
      continue
    }
    const route = edgeRoutes.get(edge.id)
    if (!route) {
      continue
    }
    left = Math.min(left, route.bounds.left)
    top = Math.min(top, route.bounds.top)
    right = Math.max(right, route.bounds.right)
    bottom = Math.max(bottom, route.bounds.bottom)
  }

  const boundsWidth = Math.max(1, right - left)
  const boundsHeight = Math.max(1, bottom - top)
  const scale = clamp(
    Math.min(usableWidth / boundsWidth, usableHeight / boundsHeight),
    MIN_SCALE,
    1.5,
  )
  return {
    scale,
    x: horizontalMargin + (usableWidth - boundsWidth * scale) / 2 - left * scale,
    y: topMargin + (usableHeight - boundsHeight * scale) / 2 - top * scale,
  }
}

function worldPoint(camera: Camera, clientX: number, clientY: number) {
  return {
    x: (clientX - camera.x) / camera.scale,
    y: (clientY - camera.y) / camera.scale,
  }
}

function nodeAtPoint(
  nodes: SchematicNode[],
  worldX: number,
  worldY: number,
): string | null {
  for (let index = nodes.length - 1; index >= 0; index -= 1) {
    const node = nodes[index]
    if (
      worldX >= node.x &&
      worldX <= node.x + node.width &&
      worldY >= node.y &&
      worldY <= node.y + node.height
    ) {
      return node.id
    }
  }
  return null
}

function drawBackground(
  ctx: CanvasRenderingContext2D,
  viewport: Viewport,
  camera: Camera,
) {
  const zoomOut = zoomOutFactor(camera.scale)
  const fill = ctx.createLinearGradient(0, 0, 0, viewport.height)
  fill.addColorStop(0, '#0d1a35')
  fill.addColorStop(0.55, '#162b58')
  fill.addColorStop(1, '#060c1c')
  ctx.fillStyle = fill
  ctx.fillRect(0, 0, viewport.width, viewport.height)

  const gridStep = camera.scale < 0.35 ? 120 : 40
  const offsetX = camera.x % (gridStep * camera.scale)
  const offsetY = camera.y % (gridStep * camera.scale)

  ctx.save()
  ctx.strokeStyle = `rgba(141, 176, 234, ${0.08 + zoomOut * 0.05})`
  ctx.lineWidth = 1
  for (let x = offsetX; x < viewport.width; x += gridStep * camera.scale) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, viewport.height)
    ctx.stroke()
  }
  for (let y = offsetY; y < viewport.height; y += gridStep * camera.scale) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(viewport.width, y)
    ctx.stroke()
  }
  ctx.restore()
}

function nodePalette(node: SchematicNode): { light: string; dark: string; accent: string } {
  if (node.role === 'port-in') {
    return { light: '#abd9ff', dark: '#356594', accent: '#9fd8ff' }
  }
  if (node.role === 'port-out') {
    return { light: '#ffd78e', dark: '#8f6225', accent: '#ffd36a' }
  }
  if (node.role === 'port-inout') {
    return { light: '#d9cbff', dark: '#65539a', accent: '#d8bbff' }
  }
  if (node.kind.includes('Memory')) {
    return { light: '#bdd7ff', dark: '#416ea6', accent: '#8ec5ff' }
  }
  if (node.kind.includes('Latch')) {
    return { light: '#d3c2ff', dark: '#6f59a5', accent: '#c8afff' }
  }
  if (node.kind === 'kInstance' || node.kind === 'kBlackbox') {
    return { light: '#ffe19b', dark: '#956b2c', accent: '#ffd46f' }
  }
  if (node.kind.includes('Register')) {
    return { light: '#c8d9ff', dark: '#5474a2', accent: '#accbff' }
  }
  if (node.role === 'value') {
    return { light: '#a8dbde', dark: '#2f7278', accent: '#98d8dd' }
  }
  return { light: '#9fcbff', dark: '#2d628e', accent: '#92c6ff' }
}

function nodeFill(node: SchematicNode, emphasis: number): string {
  const deepen = 0.24 + emphasis * 0.3
  const palette = nodePalette(node)
  return mixHex(palette.light, palette.dark, deepen)
}

function isReadPortNode(node: SchematicNode): boolean {
  return node.role === 'op' && (node.kind === 'kRegisterReadPort' || node.kind === 'kLatchReadPort')
}

function isWritePortNode(node: SchematicNode): boolean {
  return node.role === 'op' && (node.kind === 'kRegisterWritePort' || node.kind === 'kLatchWritePort')
}

function collapsedPortGroupId(node: SchematicNode, expansion: PortExpansionState): string | null {
  if (node.role === 'port-in' && !expansion.inputsExpanded) {
    return '__collapsed_inputs__'
  }
  if (node.role === 'port-out' && !expansion.outputsExpanded) {
    return '__collapsed_outputs__'
  }
  return null
}

function buildCollapsedPortNode(
  id: string,
  label: string,
  role: 'port-in' | 'port-out',
  nodes: SchematicNode[],
): RenderNode {
  const centerY =
    nodes.reduce((sum, node) => sum + node.y + node.height / 2, 0) / Math.max(nodes.length, 1)
  const width = 92
  const height = 34
  const minX = Math.min(...nodes.map((node) => node.x))
  const maxX = Math.max(...nodes.map((node) => node.x + node.width))

  return {
    id,
    label,
    secondaryLabel: `${nodes.length} ports`,
    kind: 'kCollapsedPortGroup',
    navigationPath: null,
    navigationSymbol: null,
    role,
    layer: role === 'port-in' ? 0 : Math.max(...nodes.map((node) => node.layer), 0),
    x: role === 'port-in' ? minX : maxX - width,
    y: centerY - height / 2,
    width,
    height,
    inputs: [],
    outputs: [],
    attrs: [['count', String(nodes.length)]],
    originalIds: nodes.map((node) => node.id),
    syntheticGroup: role === 'port-in' ? 'inputs' : 'outputs',
  }
}

function buildRenderGraph(graph: GraphDetail, expansion: PortExpansionState): RenderGraph {
  const renderNodes: RenderNode[] = []
  const hiddenInputNodes: SchematicNode[] = []
  const hiddenOutputNodes: SchematicNode[] = []

  for (const node of graph.nodes) {
    const collapsedId = collapsedPortGroupId(node, expansion)
    if (collapsedId === '__collapsed_inputs__') {
      hiddenInputNodes.push(node)
      continue
    }
    if (collapsedId === '__collapsed_outputs__') {
      hiddenOutputNodes.push(node)
      continue
    }
    renderNodes.push({
      ...node,
      originalIds: [node.id],
      syntheticGroup: null,
    })
  }

  if (hiddenInputNodes.length > 0) {
    renderNodes.push(buildCollapsedPortNode('__collapsed_inputs__', 'Inputs', 'port-in', hiddenInputNodes))
  }
  if (hiddenOutputNodes.length > 0) {
    renderNodes.push(buildCollapsedPortNode('__collapsed_outputs__', 'Outputs', 'port-out', hiddenOutputNodes))
  }

  const renderNodeIndexById = new Map(renderNodes.map((node, index) => [node.id, index]))
  const edgeGroups = new Map<
    string,
    {
      sourceId: string
      targetId: string
      kind: SchematicEdge['kind']
      weight: number
      sourceNodeIds: Set<string>
      targetNodeIds: Set<string>
      valueIds: Set<string>
    }
  >()

  for (const edge of graph.edges) {
    const sourceNode = graph.nodes[edge.source]
    const targetNode = graph.nodes[edge.target]
    if (!sourceNode || !targetNode) {
      continue
    }
    const renderSourceId = collapsedPortGroupId(sourceNode, expansion) ?? sourceNode.id
    const renderTargetId = collapsedPortGroupId(targetNode, expansion) ?? targetNode.id
    if (!renderNodeIndexById.has(renderSourceId) || !renderNodeIndexById.has(renderTargetId)) {
      continue
    }
    if (renderSourceId === renderTargetId) {
      continue
    }

    const isCollapsedPortEdge = renderSourceId !== sourceNode.id || renderTargetId !== targetNode.id
    const kind = isCollapsedPortEdge ? 'port' : edge.kind
    const key = `${renderSourceId}::${renderTargetId}::${kind}`
    const entry = edgeGroups.get(key) ?? {
      sourceId: renderSourceId,
      targetId: renderTargetId,
      kind,
      weight: 0,
      sourceNodeIds: new Set<string>(),
      targetNodeIds: new Set<string>(),
      valueIds: new Set<string>(),
    }

    entry.weight += edge.weight
    entry.sourceNodeIds.add(sourceNode.id)
    entry.targetNodeIds.add(targetNode.id)
    if (edge.valueId) {
      entry.valueIds.add(edge.valueId)
    }
    edgeGroups.set(key, entry)
  }

  const renderEdges: RenderEdge[] = []
  let edgeIndex = 0
  for (const entry of edgeGroups.values()) {
    renderEdges.push({
      id: `render:${entry.sourceId}:${entry.targetId}:${edgeIndex}`,
      source: renderNodeIndexById.get(entry.sourceId) ?? 0,
      target: renderNodeIndexById.get(entry.targetId) ?? 0,
      weight: entry.weight,
      kind: entry.kind,
      valueId: entry.valueIds.size === 1 ? [...entry.valueIds][0] : null,
      sourceId: entry.sourceId,
      targetId: entry.targetId,
      sourceNodeIds: [...entry.sourceNodeIds],
      targetNodeIds: [...entry.targetNodeIds],
      aggregatedValueIds: [...entry.valueIds],
    })
    edgeIndex += 1
  }

  const inputGroupNode = renderNodes.find((node) => node.id === '__collapsed_inputs__')
  if (inputGroupNode) {
    const anchorCenters = renderEdges
      .filter((edge) => edge.sourceId === inputGroupNode.id)
      .map((edge) => renderNodes[edge.target])
      .filter((node): node is RenderNode => Boolean(node))
      .map((node) => node.y + node.height / 2)
    if (anchorCenters.length > 0) {
      const centerY = anchorCenters.reduce((sum, value) => sum + value, 0) / anchorCenters.length
      inputGroupNode.y = centerY - inputGroupNode.height / 2
    }
  }

  const outputGroupNode = renderNodes.find((node) => node.id === '__collapsed_outputs__')
  if (outputGroupNode) {
    const anchorCenters = renderEdges
      .filter((edge) => edge.targetId === outputGroupNode.id)
      .map((edge) => renderNodes[edge.source])
      .filter((node): node is RenderNode => Boolean(node))
      .map((node) => node.y + node.height / 2)
    if (anchorCenters.length > 0) {
      const centerY = anchorCenters.reduce((sum, value) => sum + value, 0) / anchorCenters.length
      outputGroupNode.y = centerY - outputGroupNode.height / 2
    }
  }

  return {
    nodes: renderNodes,
    edges: renderEdges,
  }
}

function drawNodeShape(ctx: CanvasRenderingContext2D, node: SchematicNode) {
  const { x, y, width, height } = node
  if (node.role === 'port-in') {
    const nose = Math.min(18, width * 0.2)
    ctx.moveTo(x, y + 4)
    ctx.lineTo(x + width - nose, y + 4)
    ctx.lineTo(x + width, y + height / 2)
    ctx.lineTo(x + width - nose, y + height - 4)
    ctx.lineTo(x, y + height - 4)
    ctx.closePath()
    return
  }
  if (node.role === 'port-out') {
    const nose = Math.min(18, width * 0.2)
    ctx.moveTo(x + nose, y + 4)
    ctx.lineTo(x + width, y + 4)
    ctx.lineTo(x + width, y + height - 4)
    ctx.lineTo(x + nose, y + height - 4)
    ctx.lineTo(x, y + height / 2)
    ctx.closePath()
    return
  }
  if (node.role === 'port-inout') {
    const nose = Math.min(16, width * 0.16)
    ctx.moveTo(x + nose, y + 4)
    ctx.lineTo(x + width - nose, y + 4)
    ctx.lineTo(x + width, y + height / 2)
    ctx.lineTo(x + width - nose, y + height - 4)
    ctx.lineTo(x + nose, y + height - 4)
    ctx.lineTo(x, y + height / 2)
    ctx.closePath()
    return
  }
  if (isReadPortNode(node)) {
    const nose = Math.min(16, width * 0.16)
    ctx.moveTo(x + 2, y + 4)
    ctx.lineTo(x + width - nose, y + 4)
    ctx.lineTo(x + width, y + height / 2)
    ctx.lineTo(x + width - nose, y + height - 4)
    ctx.lineTo(x + 2, y + height - 4)
    ctx.lineTo(x + 10, y + height / 2)
    ctx.closePath()
    return
  }
  if (isWritePortNode(node)) {
    const nose = Math.min(16, width * 0.16)
    ctx.moveTo(x + nose, y + 4)
    ctx.lineTo(x + width - 2, y + 4)
    ctx.lineTo(x + width - 10, y + height / 2)
    ctx.lineTo(x + width - 2, y + height - 4)
    ctx.lineTo(x + nose, y + height - 4)
    ctx.lineTo(x, y + height / 2)
    ctx.closePath()
    return
  }
  ctx.roundRect(x, y, width, height, 8)
}

function drawNodeDecoration(
  ctx: CanvasRenderingContext2D,
  node: SchematicNode,
  scale: number,
  isDimmed: boolean,
) {
  const emphasis = zoomOutFactor(scale)
  if (scale < 0.52) {
    return
  }
  if (!(isReadPortNode(node) || isWritePortNode(node) || node.role.startsWith('port'))) {
    return
  }

  ctx.save()
  ctx.globalAlpha = isDimmed ? 0.45 : 0.9
  ctx.strokeStyle = nodePalette(node).accent
  ctx.lineWidth = 1.2 + emphasis * 0.5
  const centerY = node.y + node.height / 2
  const left = node.x + 14
  const right = node.x + Math.min(node.width - 18, left + 22)

  if (node.kind.includes('Memory')) {
    ctx.beginPath()
    ctx.moveTo(left, centerY - 6)
    ctx.lineTo(right, centerY - 6)
    ctx.moveTo(left, centerY)
    ctx.lineTo(right, centerY)
    ctx.moveTo(left, centerY + 6)
    ctx.lineTo(right, centerY + 6)
    ctx.stroke()
  } else if (node.kind.includes('Latch')) {
    ctx.beginPath()
    ctx.moveTo(left, centerY - 7)
    ctx.lineTo(left + 10, centerY)
    ctx.lineTo(left, centerY + 7)
    ctx.lineTo(left, centerY - 7)
    ctx.moveTo(left + 12, centerY - 7)
    ctx.lineTo(left + 12, centerY + 7)
    ctx.stroke()
  } else if (isReadPortNode(node) || isWritePortNode(node)) {
    ctx.beginPath()
    ctx.moveTo(left, centerY)
    ctx.lineTo(right, centerY)
    ctx.moveTo(right - 6, centerY - 4)
    ctx.lineTo(right, centerY)
    ctx.lineTo(right - 6, centerY + 4)
    ctx.stroke()
  }
  ctx.restore()
}

function drawEdge(
  ctx: CanvasRenderingContext2D,
  route: EdgeRoute,
  visibleLeft: number,
  visibleRight: number,
  visibleTop: number,
  visibleBottom: number,
) {
  if (
    route.bounds.right < visibleLeft ||
    route.bounds.left > visibleRight ||
    route.bounds.bottom < visibleTop ||
    route.bounds.top > visibleBottom
  ) {
    return
  }

  ctx.beginPath()
  ctx.moveTo(route.x1, route.y1)
  ctx.bezierCurveTo(route.x2, route.y2, route.x3, route.y3, route.x4, route.y4)
  ctx.stroke()
}

function bezierPoint(route: EdgeRoute, t: number): EdgePoint {
  const mt = 1 - t
  return {
    x:
      mt * mt * mt * route.x1 +
      3 * mt * mt * t * route.x2 +
      3 * mt * t * t * route.x3 +
      t * t * t * route.x4,
    y:
      mt * mt * mt * route.y1 +
      3 * mt * mt * t * route.y2 +
      3 * mt * t * t * route.y3 +
      t * t * t * route.y4,
  }
}

function sampledRouteBounds(route: Omit<EdgeRoute, 'midpoint' | 'bounds'>) {
  let left = Number.POSITIVE_INFINITY
  let right = Number.NEGATIVE_INFINITY
  let top = Number.POSITIVE_INFINITY
  let bottom = Number.NEGATIVE_INFINITY

  for (let step = 0; step <= 24; step += 1) {
    const point = bezierPoint(route as EdgeRoute, step / 24)
    left = Math.min(left, point.x)
    right = Math.max(right, point.x)
    top = Math.min(top, point.y)
    bottom = Math.max(bottom, point.y)
  }

  return { left, right, top, bottom }
}

function createEdgeRoute(route: Omit<EdgeRoute, 'midpoint' | 'bounds'>): EdgeRoute {
  return {
    ...route,
    midpoint: bezierPoint(route as EdgeRoute, 0.5),
    bounds: sampledRouteBounds(route),
  }
}

function edgeEndpoints(edge: SchematicEdge, nodes: SchematicNode[]) {
  const source = nodes[edge.source]
  const target = nodes[edge.target]
  return {
    x1: source.x + source.width,
    y1: source.y + source.height / 2,
    x4: target.x,
    y4: target.y + target.height / 2,
    sourceWidth: source.width,
    targetWidth: target.width,
  }
}

function computeEdgeRoutes(renderGraph: RenderGraph): Map<string, EdgeRoute> {
  const routes = new Map<string, EdgeRoute>()
  const forwardGroups = new Map<string, RenderEdge[]>()
  const backedgeGroups = new Map<string, RenderEdge[]>()

  for (const edge of renderGraph.edges) {
    const sourceLayer = renderGraph.nodes[edge.source]?.layer ?? 0
    const targetLayer = renderGraph.nodes[edge.target]?.layer ?? sourceLayer
    const key = `${sourceLayer}:${targetLayer}:${edge.kind}`
    const groups = edge.kind === 'backedge' ? backedgeGroups : forwardGroups
    const bucket = groups.get(key)
    if (bucket) {
      bucket.push(edge)
    } else {
      groups.set(key, [edge])
    }
  }

  const buildForwardRoute = (edge: RenderEdge, slot: number): EdgeRoute => {
    const { x1, y1, x4, y4, sourceWidth, targetWidth } = edgeEndpoints(edge, renderGraph.nodes)
    const span = Math.max(24, x4 - x1)
    const sourceTangent = Math.min(224, Math.max(96, sourceWidth * 0.78))
    const targetTangent = Math.min(184, Math.max(82, targetWidth * 0.68))
    const minGap = Math.max(32, span * 0.14)
    const leftLimit = x1 + 16
    const rightLimit = x4 - 16
    const preferredExitX = x1 + Math.min(span * 0.7, sourceTangent)
    const preferredEntryX = x4 - Math.min(span * 0.56, targetTangent)

    let exitX = clamp(preferredExitX + slot * 6, leftLimit, Math.max(leftLimit, rightLimit - minGap))
    let entryX = clamp(preferredEntryX + slot * 3, Math.min(rightLimit, exitX + minGap), rightLimit)

    if (entryX - exitX < minGap) {
      const centerX = clamp(x1 + span * 0.5, leftLimit + minGap / 2, rightLimit - minGap / 2)
      exitX = centerX - minGap / 2
      entryX = centerX + minGap / 2
    }

    return createEdgeRoute({
      x1,
      y1,
      x2: exitX,
      y2: y1,
      x3: entryX,
      y3: y4,
      x4,
      y4,
    })
  }

  const buildBackedgeRoute = (edge: RenderEdge, slot: number): EdgeRoute => {
    const { x1, y1, x4, y4, sourceWidth, targetWidth } = edgeEndpoints(edge, renderGraph.nodes)
    const sourceTangent = Math.min(260, Math.max(118, sourceWidth * 0.9)) + Math.abs(slot) * 18
    const targetTangent = Math.min(212, Math.max(96, targetWidth * 0.74)) + Math.abs(slot) * 12
    const exitX = x1 + sourceTangent
    const entryX = x4 - targetTangent
    return createEdgeRoute({
      x1,
      y1,
      x2: exitX,
      y2: y1,
      x3: entryX,
      y3: y4,
      x4,
      y4,
    })
  }

  for (const group of forwardGroups.values()) {
    group
      .slice()
      .sort((left, right) => {
        const leftCenter =
          (renderGraph.nodes[left.source]?.y ?? 0) + (renderGraph.nodes[left.target]?.y ?? 0)
        const rightCenter =
          (renderGraph.nodes[right.source]?.y ?? 0) + (renderGraph.nodes[right.target]?.y ?? 0)
        return leftCenter - rightCenter || left.id.localeCompare(right.id)
      })
      .forEach((edge, index, edges) => {
        const slot = index - (edges.length - 1) / 2
        routes.set(edge.id, buildForwardRoute(edge, slot))
      })
  }

  for (const group of backedgeGroups.values()) {
    group
      .slice()
      .sort((left, right) => {
        const leftCenter = renderGraph.nodes[left.target]?.y ?? 0
        const rightCenter = renderGraph.nodes[right.target]?.y ?? 0
        return leftCenter - rightCenter || left.id.localeCompare(right.id)
      })
      .forEach((edge, index) => {
        routes.set(edge.id, buildBackedgeRoute(edge, index))
      })
  }

  return routes
}

function distanceToEdge(route: EdgeRoute, x: number, y: number): number {
  let minDistance = Number.POSITIVE_INFINITY
  for (let step = 0; step <= 24; step += 1) {
    const point = bezierPoint(route, step / 24)
    minDistance = Math.min(minDistance, Math.hypot(point.x - x, point.y - y))
  }
  return minDistance
}

function edgeAtPoint(
  edges: RenderEdge[],
  edgeRoutes: Map<string, EdgeRoute>,
  worldX: number,
  worldY: number,
  hitRadius = 18,
): RenderEdge | null {
  let bestEdge: RenderEdge | null = null
  let bestDistance = hitRadius
  for (const edge of edges) {
    const route = edgeRoutes.get(edge.id)
    if (!route) {
      continue
    }
    const distance = distanceToEdge(route, worldX, worldY)
    if (distance < bestDistance) {
      bestDistance = distance
      bestEdge = edge
    }
  }
  return bestEdge
}

function valueAtPoint(
  edges: SchematicEdge[],
  edgeRoutes: Map<string, EdgeRoute>,
  worldX: number,
  worldY: number,
  hitRadius = 18,
): string | null {
  let bestValueId: string | null = null
  let bestDistance = hitRadius
  for (const edge of edges) {
    if (!edge.valueId) {
      continue
    }
    const route = edgeRoutes.get(edge.id)
    if (!route) {
      continue
    }
    const distance = distanceToEdge(route, worldX, worldY)
    if (distance < bestDistance) {
      bestDistance = distance
      bestValueId = edge.valueId
    }
  }
  return bestValueId
}

function trimTextToWidth(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (maxWidth <= 0 || ctx.measureText(text).width <= maxWidth) {
    return text
  }

  const ellipsis = '…'
  let trimmed = text
  while (trimmed.length > 1 && ctx.measureText(`${trimmed}${ellipsis}`).width > maxWidth) {
    trimmed = trimmed.slice(0, -1)
  }
  return `${trimmed}${ellipsis}`
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  node: SchematicNode,
  scale: number,
  isSelected: boolean,
  isHovered: boolean,
  isConnected: boolean,
  isDimmed: boolean,
) {
  const emphasis = zoomOutFactor(scale)
  if (isSelected) {
    ctx.save()
    ctx.beginPath()
    drawNodeShape(ctx, node)
    ctx.globalAlpha = isDimmed ? 0.26 : 1
    ctx.lineWidth = 5.8 + emphasis * 1.1
    ctx.strokeStyle = rgbaHex('#70a9ff', 0.26 + emphasis * 0.12)
    ctx.shadowColor = rgbaHex('#9fccff', 0.32 + emphasis * 0.14)
    ctx.shadowBlur = 12 + emphasis * 10
    ctx.stroke()
    ctx.restore()
  }

  ctx.beginPath()
  drawNodeShape(ctx, node)
  ctx.globalAlpha = isDimmed ? 0.22 : 1
  ctx.fillStyle = nodeFill(node, emphasis)
  ctx.fill()
  ctx.lineWidth = isSelected ? 2.2 + emphasis * 0.5 : isConnected ? 2.45 + emphasis * 0.5 : isHovered ? 2.2 + emphasis * 0.45 : 1.35 + emphasis * 0.9
  ctx.strokeStyle = isSelected
    ? '#dcecff'
    : isConnected
      ? '#99cbff'
      : isHovered
        ? '#f4d48b'
        : '#163455'
  ctx.stroke()
  ctx.globalAlpha = isDimmed ? 0.38 : 1

  if (scale < 0.45) {
    ctx.globalAlpha = 1
    return
  }
  const labelFontSize = scale >= 1.1 ? 19 : scale >= 0.9 ? 17 : 15
  const secondaryFontSize = scale >= 1.1 ? 15 : scale >= 0.9 ? 14 : 12
  const horizontalPadding = node.role === 'value' ? 14 : 13
  const textLeft = node.x + horizontalPadding
  const textWidth = node.width - horizontalPadding * 2
  const secondaryGap = node.secondaryLabel ? 5 : 0
  const textBlockHeight = labelFontSize + (node.secondaryLabel ? secondaryGap + secondaryFontSize : 0)
  const textTop = node.y + Math.max(5, (node.height - textBlockHeight) / 2 - 1)

  ctx.save()
  ctx.beginPath()
  if (node.role === 'op') {
    ctx.roundRect(node.x + 1, node.y + 1, node.width - 2, node.height - 2, 8)
  } else {
    ctx.rect(node.x + 4, node.y + 3, Math.max(1, node.width - 8), Math.max(1, node.height - 6))
  }
  ctx.clip()

  ctx.fillStyle = '#08111f'
  ctx.font = `600 ${labelFontSize}px ui-sans-serif, sans-serif`
  ctx.textBaseline = 'top'
  ctx.fillText(trimTextToWidth(ctx, node.label, textWidth), textLeft, textTop)
  if (scale >= 0.75 && node.secondaryLabel) {
    ctx.fillStyle = '#20446c'
    ctx.font = `${secondaryFontSize}px ui-sans-serif, sans-serif`
    ctx.fillText(
      trimTextToWidth(ctx, node.secondaryLabel, textWidth),
      textLeft,
      textTop + labelFontSize + secondaryGap,
    )
  }
  ctx.restore()
  ctx.globalAlpha = 1
}

export default function GraphCanvas({
  graph,
  fitSignal,
  selectedNodeId,
  onSelectNode,
  onOpenNode,
  onFitView,
  onGoUpOneLevel,
  canGoUpOneLevel = false,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dragRef = useRef<DragState | null>(null)
  const [viewport, setViewport] = useState<Viewport>({ width: 0, height: 0 })
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, scale: 1 })
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [portExpansion, setPortExpansion] = useState<PortExpansionState>({
    inputsExpanded: true,
    outputsExpanded: true,
  })

  useEffect(() => {
    setPortExpansion({ inputsExpanded: true, outputsExpanded: true })
  }, [graph?.symbol, graph?.instancePath])

  const renderGraph = useMemo<RenderGraph | null>(() => {
    if (!graph) {
      return null
    }
    return buildRenderGraph(graph, portExpansion)
  }, [graph, portExpansion])

  const selectedValue = useMemo<SchematicValue | null>(() => {
    if (!graph || !selectedNodeId) {
      return null
    }
    return graph.values.find((value) => value.id === selectedNodeId) ?? null
  }, [graph, selectedNodeId])

  const selectedRenderNodeId = useMemo(() => {
    if (!renderGraph || !selectedNodeId) {
      return null
    }
    return renderGraph.nodes.some((node) => node.id === selectedNodeId) ? selectedNodeId : null
  }, [renderGraph, selectedNodeId])

  const edgeRoutes = useMemo(() => {
    if (!renderGraph) {
      return new Map<string, EdgeRoute>()
    }
    return computeEdgeRoutes(renderGraph)
  }, [renderGraph])

  const highlightState = useMemo(() => {
    if (!renderGraph || !selectedNodeId) {
      return {
        nodeIds: new Set<string>(),
        edgeIds: new Set<string>(),
      }
    }
    const nodeIds = new Set<string>()
    const edgeIds = new Set<string>()
    if (selectedValue) {
      for (const edge of renderGraph.edges) {
        if (!edge.aggregatedValueIds.includes(selectedValue.id)) {
          continue
        }
        edgeIds.add(edge.id)
        nodeIds.add(edge.sourceId)
        nodeIds.add(edge.targetId)
      }
      return { nodeIds, edgeIds }
    }

    if (selectedRenderNodeId) {
      nodeIds.add(selectedRenderNodeId)
    }
    for (const edge of renderGraph.edges) {
      if (
        edge.sourceNodeIds.includes(selectedNodeId) ||
        edge.targetNodeIds.includes(selectedNodeId) ||
        edge.sourceId === selectedNodeId ||
        edge.targetId === selectedNodeId
      ) {
        edgeIds.add(edge.id)
        nodeIds.add(edge.sourceId)
        nodeIds.add(edge.targetId)
      }
    }
    return { nodeIds, edgeIds }
  }, [renderGraph, selectedNodeId, selectedRenderNodeId, selectedValue])

  useEffect(() => {
    const element = containerRef.current
    if (!element) {
      return
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) {
        return
      }
      setViewport({
        width: Math.floor(entry.contentRect.width),
        height: Math.floor(entry.contentRect.height),
      })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!renderGraph || viewport.width === 0 || viewport.height === 0) {
      return
    }
    setCamera(fitGraphToNodes(renderGraph.nodes, renderGraph.edges, edgeRoutes, viewport))
  }, [edgeRoutes, fitSignal, renderGraph, viewport])

  function centerNode(nodeId: string) {
    if (!renderGraph || viewport.width === 0 || viewport.height === 0) {
      return
    }
    const node = renderGraph.nodes.find((candidate) => candidate.id === nodeId)
    if (!node) {
      return
    }
    setCamera((current) => ({
      ...current,
      x: viewport.width / 2 - (node.x + node.width / 2) * current.scale,
      y: viewport.height / 2 - (node.y + node.height / 2) * current.scale,
    }))
  }

  function focusValueSource(valueId: string) {
    if (!graph) {
      return
    }
    const value = graph.values.find((candidate) => candidate.id === valueId)
    if (!value) {
      return
    }
    const sourceNode = value.sourceId
      ? graph.nodes.find((candidate) => candidate.id === value.sourceId)
      : null
    if (sourceNode?.role === 'op') {
      centerNode(sourceNode.id)
      return
    }
    const firstOpTarget = value.targetIds
      .map((targetId) => graph.nodes.find((candidate) => candidate.id === targetId))
      .find((candidate) => candidate?.role === 'op')
    if (firstOpTarget) {
      centerNode(firstOpTarget.id)
    }
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || viewport.width === 0 || viewport.height === 0) {
      return
    }
    const backingStore = computeBackingStore(viewport, window.devicePixelRatio || 1)
    canvas.width = backingStore.pixelWidth
    canvas.height = backingStore.pixelHeight
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`

    const context = canvas.getContext('2d')
    if (!context) {
      return
    }
    context.setTransform(backingStore.renderScale, 0, 0, backingStore.renderScale, 0, 0)
    drawBackground(context, viewport, camera)

    if (!graph || !renderGraph) {
      return
    }

    const visibleLeft = -camera.x / camera.scale
    const visibleTop = -camera.y / camera.scale
    const visibleRight = visibleLeft + viewport.width / camera.scale
    const visibleBottom = visibleTop + viewport.height / camera.scale

    context.save()
    context.translate(camera.x, camera.y)
    context.scale(camera.scale, camera.scale)
    context.lineJoin = 'round'
    context.lineCap = 'round'

    const emphasis = zoomOutFactor(camera.scale)
    context.lineWidth = 1.25 + emphasis * 0.65
    for (const edge of renderGraph.edges) {
      const route = edgeRoutes.get(edge.id)
      if (!route) {
        continue
      }
      const isHighlighted = highlightState.edgeIds.has(edge.id)
      const hasSelection = selectedNodeId !== null
      context.strokeStyle = isHighlighted
        ? edge.kind === 'backedge'
          ? rgbaHex('#ffd166', 0.94)
          : rgbaHex('#98c7ff', 0.98)
        : edge.kind === 'backedge'
          ? hasSelection
            ? rgbaHex('#f0b85d', 0.24 + emphasis * 0.12)
            : rgbaHex('#f0b85d', 0.52 + emphasis * 0.24)
          : hasSelection
            ? rgbaHex('#8ab7ff', 0.22 + emphasis * 0.12)
            : rgbaHex('#8ab7ff', 0.48 + emphasis * 0.26)
      context.lineWidth = isHighlighted ? 2.35 + emphasis * 0.75 : 1.2 + emphasis * 1.2
      drawEdge(context, route, visibleLeft, visibleRight, visibleTop, visibleBottom)
    }

    if (selectedValue && highlightState.edgeIds.size > 0) {
      const midpoints = renderGraph.edges
        .filter((edge) => highlightState.edgeIds.has(edge.id))
        .map((edge) => edgeRoutes.get(edge.id)?.midpoint ?? null)
        .filter((point): point is EdgePoint => point !== null)
      if (midpoints.length > 0) {
        const centerX = midpoints.reduce((sum, point) => sum + point.x, 0) / midpoints.length
        const centerY = midpoints.reduce((sum, point) => sum + point.y, 0) / midpoints.length
        const pillLabel = selectedValue.label
        context.font = '600 11px ui-sans-serif, sans-serif'
        const pillWidth = Math.min(180, Math.max(68, context.measureText(pillLabel).width + 24))
        const pillHeight = 26
        context.beginPath()
        context.roundRect(centerX - pillWidth / 2, centerY - pillHeight / 2, pillWidth, pillHeight, 999)
        context.fillStyle = 'rgba(248, 231, 179, 0.97)'
        context.fill()
        context.lineWidth = 1.4
        context.strokeStyle = '#f0b85d'
        context.stroke()
        context.fillStyle = '#2d1e06'
        context.textBaseline = 'middle'
        context.fillText(pillLabel, centerX - pillWidth / 2 + 12, centerY)
      }
    }

    for (let index = 0; index < renderGraph.nodes.length; index += 1) {
      const node = renderGraph.nodes[index]
      if (
        node.x + node.width < visibleLeft ||
        node.x > visibleRight ||
        node.y + node.height < visibleTop ||
        node.y > visibleBottom
      ) {
        continue
      }
      const isSelected = node.id === selectedRenderNodeId
      const isConnected = !isSelected && highlightState.nodeIds.has(node.id)
      const isDimmed = selectedNodeId !== null && !highlightState.nodeIds.has(node.id)
      drawNode(
        context,
        node,
        camera.scale,
        isSelected,
        hoveredNodeId === node.id,
        isConnected,
        isDimmed,
      )
      drawNodeDecoration(context, node, camera.scale, isDimmed)
    }
    context.restore()
  }, [camera, edgeRoutes, graph, highlightState.edgeIds, highlightState.nodeIds, hoveredNodeId, renderGraph, selectedNodeId, selectedRenderNodeId, selectedValue, viewport])

  function onWheel(event: WheelEvent<HTMLCanvasElement>) {
    if (!graph) {
      return
    }
    event.preventDefault()
    const rect = event.currentTarget.getBoundingClientRect()
    const pointerX = event.clientX - rect.left
    const pointerY = event.clientY - rect.top
    setCamera((current) => {
      const before = worldPoint(current, pointerX, pointerY)
      const nextScale = clamp(current.scale * (event.deltaY < 0 ? 1.12 : 0.9), MIN_SCALE, MAX_SCALE)
      return {
        scale: nextScale,
        x: pointerX - before.x * nextScale,
        y: pointerY - before.y * nextScale,
      }
    })
  }

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    dragRef.current = {
      pointerId: event.pointerId,
      lastX: event.clientX,
      lastY: event.clientY,
      moved: false,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    if (renderGraph) {
      const rect = event.currentTarget.getBoundingClientRect()
      const pointerX = event.clientX - rect.left
      const pointerY = event.clientY - rect.top
      const point = worldPoint(camera, pointerX, pointerY)
      setHoveredNodeId(nodeAtPoint(renderGraph.nodes, point.x, point.y))
    }
    if (!drag || drag.pointerId !== event.pointerId) {
      return
    }
    const deltaX = event.clientX - drag.lastX
    const deltaY = event.clientY - drag.lastY
    if (Math.abs(deltaX) > 1 || Math.abs(deltaY) > 1) {
      drag.moved = true
    }
    drag.lastX = event.clientX
    drag.lastY = event.clientY
    setCamera((current) => ({
      ...current,
      x: current.x + deltaX,
      y: current.y + deltaY,
    }))
  }

  function onPointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) {
      return
    }
    event.currentTarget.releasePointerCapture(event.pointerId)
    if (!drag.moved && renderGraph) {
      const rect = event.currentTarget.getBoundingClientRect()
      const pointerX = event.clientX - rect.left
      const pointerY = event.clientY - rect.top
      const point = worldPoint(camera, pointerX, pointerY)
      const nodeId = nodeAtPoint(renderGraph.nodes, point.x, point.y)
      const node = nodeId ? renderGraph.nodes.find((candidate) => candidate.id === nodeId) ?? null : null
      if (node?.syntheticGroup) {
        onSelectNode(null)
      } else {
        onSelectNode(
          nodeId ??
            valueAtPoint(
              renderGraph.edges,
              edgeRoutes,
              point.x,
              point.y,
              Math.max(18, 12 / camera.scale),
            ),
        )
      }
    }
    dragRef.current = null
  }

  function onDoubleClick(event: ReactMouseEvent<HTMLCanvasElement>) {
    if (!graph || !renderGraph) {
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    const pointerX = event.clientX - rect.left
    const pointerY = event.clientY - rect.top
    const point = worldPoint(camera, pointerX, pointerY)
    const nodeId = nodeAtPoint(renderGraph.nodes, point.x, point.y)
    const node = nodeId ? renderGraph.nodes.find((candidate) => candidate.id === nodeId) ?? null : null
    if (node?.syntheticGroup === 'inputs') {
      setPortExpansion((current) => ({ ...current, inputsExpanded: true }))
      return
    }
    if (node?.syntheticGroup === 'outputs') {
      setPortExpansion((current) => ({ ...current, outputsExpanded: true }))
      return
    }
    if (node?.kind === 'kInstance' && node.navigationPath && node.navigationSymbol && onOpenNode) {
      onOpenNode(node.id)
      return
    }
    const edge = edgeAtPoint(
      renderGraph.edges,
      edgeRoutes,
      point.x,
      point.y,
      Math.max(18, 12 / camera.scale),
    )
    if (!edge) {
      return
    }
    if (edge.valueId) {
      onSelectNode(edge.valueId)
      focusValueSource(edge.valueId)
      return
    }
    if (edge.targetId === '__collapsed_outputs__') {
      onSelectNode(edge.sourceId)
      centerNode(edge.sourceId)
      return
    }
    if (edge.sourceId === '__collapsed_inputs__') {
      onSelectNode(edge.targetId)
      centerNode(edge.targetId)
      return
    }
    const valueId = valueAtPoint(
      renderGraph.edges,
      edgeRoutes,
      point.x,
      point.y,
      Math.max(18, 12 / camera.scale),
    )
    if (!valueId) {
      return
    }
    onSelectNode(valueId)
    focusValueSource(valueId)
  }

  return (
    <div className="graph-canvas-root" ref={containerRef}>
      <canvas
        ref={canvasRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDoubleClick={onDoubleClick}
        onPointerLeave={() => setHoveredNodeId(null)}
      />
      {graph && (onFitView || canGoUpOneLevel || selectedNodeId) ? (
        <div className="graph-canvas-toolbar">
          {onFitView ? (
            <button type="button" className="canvas-tool-button" onClick={onFitView}>
              Fit to view
            </button>
          ) : null}
          {canGoUpOneLevel && onGoUpOneLevel ? (
            <button type="button" className="canvas-tool-button" onClick={onGoUpOneLevel}>
              Up one level
            </button>
          ) : null}
          {selectedNodeId ? (
            <button type="button" className="canvas-tool-button" onClick={() => onSelectNode(null)}>
              Clear highlight
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="canvas-hint">
        drag to pan · wheel to zoom · click highlight · double-click value focus
      </div>
    </div>
  )
}
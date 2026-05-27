import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from 'react'
import type { GraphDetail, SchematicEdge, SchematicNode } from '../lib/grh'

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
}

const MIN_SCALE = 0.15
const MAX_SCALE = 2.5

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function fitGraph(graph: GraphDetail, viewport: Viewport): Camera {
  const margin = 56
  const usableWidth = Math.max(viewport.width - margin * 2, 200)
  const usableHeight = Math.max(viewport.height - margin * 2, 160)
  const scale = clamp(
    Math.min(usableWidth / Math.max(graph.width, 1), usableHeight / Math.max(graph.height, 1)),
    MIN_SCALE,
    1.2,
  )
  return {
    scale,
    x: (viewport.width - graph.width * scale) / 2,
    y: (viewport.height - graph.height * scale) / 2,
  }
}

function worldPoint(camera: Camera, clientX: number, clientY: number) {
  return {
    x: (clientX - camera.x) / camera.scale,
    y: (clientY - camera.y) / camera.scale,
  }
}

function nodeAtPoint(graph: GraphDetail, worldX: number, worldY: number): string | null {
  for (let index = graph.nodes.length - 1; index >= 0; index -= 1) {
    const node = graph.nodes[index]
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
  ctx.fillStyle = '#f3efe5'
  ctx.fillRect(0, 0, viewport.width, viewport.height)

  const gridStep = camera.scale < 0.35 ? 120 : 40
  const offsetX = camera.x % (gridStep * camera.scale)
  const offsetY = camera.y % (gridStep * camera.scale)

  ctx.save()
  ctx.strokeStyle = 'rgba(52, 67, 78, 0.08)'
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

function nodeFill(node: SchematicNode): string {
  if (node.role === 'port-in') {
    return '#dbeafe'
  }
  if (node.role === 'port-out') {
    return '#fee2e2'
  }
  if (node.role === 'port-inout') {
    return '#ede9fe'
  }
  if (node.kind === 'kInstance' || node.kind === 'kBlackbox') {
    return '#fde68a'
  }
  if (node.kind.includes('Memory') || node.kind.includes('Register')) {
    return '#bfdbfe'
  }
  return '#d1fae5'
}

function drawEdge(
  ctx: CanvasRenderingContext2D,
  edge: SchematicEdge,
  nodes: SchematicNode[],
  visibleLeft: number,
  visibleRight: number,
  visibleTop: number,
  visibleBottom: number,
) {
  const source = nodes[edge.source]
  const target = nodes[edge.target]
  const minX = Math.min(source.x, target.x)
  const maxX = Math.max(source.x + source.width, target.x + target.width)
  const minY = Math.min(source.y, target.y)
  const maxY = Math.max(source.y + source.height, target.y + target.height)
  if (
    maxX < visibleLeft ||
    minX > visibleRight ||
    maxY < visibleTop ||
    minY > visibleBottom
  ) {
    return
  }

  const x1 = source.x + source.width
  const y1 = source.y + source.height / 2
  const x4 = target.x
  const y4 = target.y + target.height / 2

  ctx.beginPath()
  if (edge.kind === 'backedge') {
    const loopX = Math.max(x1, x4) + 96
    ctx.moveTo(x1, y1)
    ctx.bezierCurveTo(loopX, y1, loopX, y4, x4, y4)
  } else {
    const midX = x1 + Math.max((x4 - x1) * 0.55, 32)
    ctx.moveTo(x1, y1)
    ctx.bezierCurveTo(midX, y1, midX, y4, x4, y4)
  }
  ctx.stroke()
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  node: SchematicNode,
  scale: number,
  isSelected: boolean,
  isHovered: boolean,
) {
  const radius = node.role === 'op' ? 8 : 12
  ctx.beginPath()
  ctx.roundRect(node.x, node.y, node.width, node.height, radius)
  ctx.fillStyle = nodeFill(node)
  ctx.fill()
  ctx.lineWidth = isSelected ? 3 : isHovered ? 2 : 1.25
  ctx.strokeStyle = isSelected ? '#9a3412' : isHovered ? '#92400e' : '#334155'
  ctx.stroke()

  if (scale < 0.35) {
    return
  }
  ctx.fillStyle = '#0f172a'
  ctx.font = `${Math.max(10, Math.round(11 / scale + 6))}px ui-monospace, monospace`
  ctx.textBaseline = 'top'
  ctx.fillText(node.label, node.x + 10, node.y + 8)
  if (scale >= 0.6 && node.secondaryLabel) {
    ctx.fillStyle = '#475569'
    ctx.fillText(node.secondaryLabel, node.x + 10, node.y + 24)
  }
}

export default function GraphCanvas({
  graph,
  fitSignal,
  selectedNodeId,
  onSelectNode,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dragRef = useRef<DragState | null>(null)
  const [viewport, setViewport] = useState<Viewport>({ width: 0, height: 0 })
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, scale: 1 })
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)

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
    if (!graph || viewport.width === 0 || viewport.height === 0) {
      return
    }
    setCamera(fitGraph(graph, viewport))
  }, [fitSignal, graph, viewport])

  const selectedIndex = useMemo(() => {
    if (!graph || !selectedNodeId) {
      return -1
    }
    return graph.nodes.findIndex((node) => node.id === selectedNodeId)
  }, [graph, selectedNodeId])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || viewport.width === 0 || viewport.height === 0) {
      return
    }
    canvas.width = Math.floor(viewport.width * window.devicePixelRatio)
    canvas.height = Math.floor(viewport.height * window.devicePixelRatio)
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`

    const context = canvas.getContext('2d')
    if (!context) {
      return
    }
    context.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0)
    drawBackground(context, viewport, camera)

    if (!graph) {
      context.fillStyle = '#475569'
      context.font = '15px ui-sans-serif, sans-serif'
      context.fillText('Load a GRH design to render a graph.', 28, 32)
      return
    }

    const visibleLeft = -camera.x / camera.scale
    const visibleTop = -camera.y / camera.scale
    const visibleRight = visibleLeft + viewport.width / camera.scale
    const visibleBottom = visibleTop + viewport.height / camera.scale

    context.save()
    context.translate(camera.x, camera.y)
    context.scale(camera.scale, camera.scale)

    const drawBundlesOnly = camera.scale < 0.32 || graph.edges.length > 8000
    if (drawBundlesOnly) {
      for (const bundle of graph.bundles) {
        const fromBand = graph.layerBands[bundle.fromLayer]
        const toBand = graph.layerBands[bundle.toLayer]
        if (!fromBand || !toBand) {
          continue
        }
        context.beginPath()
        context.moveTo(fromBand.x + 170, fromBand.centerY)
        context.lineTo(toBand.x, toBand.centerY)
        context.lineWidth = Math.min(10, 1.2 + Math.log2(bundle.count + 1))
        context.strokeStyle =
          bundle.kind === 'backedge'
            ? 'rgba(180, 83, 9, 0.25)'
            : 'rgba(37, 99, 235, 0.18)'
        context.stroke()
      }
    } else {
      context.lineWidth = 1.25
      for (const edge of graph.edges) {
        context.strokeStyle =
          edge.kind === 'backedge' ? 'rgba(180, 83, 9, 0.45)' : 'rgba(37, 99, 235, 0.26)'
        drawEdge(context, edge, graph.nodes, visibleLeft, visibleRight, visibleTop, visibleBottom)
      }
    }

    for (let index = 0; index < graph.nodes.length; index += 1) {
      const node = graph.nodes[index]
      if (
        node.x + node.width < visibleLeft ||
        node.x > visibleRight ||
        node.y + node.height < visibleTop ||
        node.y > visibleBottom
      ) {
        continue
      }
      drawNode(context, node, camera.scale, index === selectedIndex, hoveredNodeId === node.id)
    }
    context.restore()

    context.fillStyle = 'rgba(15, 23, 42, 0.78)'
    context.font = '12px ui-monospace, monospace'
    context.fillText(
      `zoom ${camera.scale.toFixed(2)}x  nodes ${graph.nodes.length}  edges ${graph.edges.length}`,
      18,
      22,
    )
  }, [camera, graph, hoveredNodeId, selectedIndex, viewport])

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
    if (graph) {
      const rect = event.currentTarget.getBoundingClientRect()
      const pointerX = event.clientX - rect.left
      const pointerY = event.clientY - rect.top
      const point = worldPoint(camera, pointerX, pointerY)
      setHoveredNodeId(nodeAtPoint(graph, point.x, point.y))
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
    if (!drag.moved && graph) {
      const rect = event.currentTarget.getBoundingClientRect()
      const pointerX = event.clientX - rect.left
      const pointerY = event.clientY - rect.top
      const point = worldPoint(camera, pointerX, pointerY)
      onSelectNode(nodeAtPoint(graph, point.x, point.y))
    }
    dragRef.current = null
  }

  return (
    <div className="graph-canvas-root" ref={containerRef}>
      <canvas
        ref={canvasRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHoveredNodeId(null)}
      />
      <div className="canvas-hint">drag to pan · wheel to zoom · click node to inspect</div>
    </div>
  )
}
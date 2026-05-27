import {
  attrAsString,
  attrPayloadToString,
  graphSymbol,
  type DesignOverview,
  type EdgeBundle,
  type GraphDetail,
  type GraphSummary,
  type GrhDesign,
  type GrhGraph,
  type HierarchyNode,
  type LayerBand,
  type SchematicEdge,
  type SchematicNode,
  type WorkerRequest,
  type WorkerResponse,
} from '../lib/grh'

type InstanceRef = {
  moduleName: string
  instanceName: string
}

type NormalizedGraph = {
  symbol: string
  raw: GrhGraph
  summary: GraphSummary
  instances: InstanceRef[]
}

type NormalizedDesign = {
  overview: DesignOverview
  graphsBySymbol: Map<string, NormalizedGraph>
}

let currentDesign: NormalizedDesign | null = null

function fail(requestId: number, stage: 'load-design' | 'load-graph', message: string) {
  const response: WorkerResponse = { type: 'error', requestId, stage, message }
  postMessage(response)
}

function normalizeDesign(payload: GrhDesign): NormalizedDesign {
  const rawGraphs = payload.graphs ?? []
  if (rawGraphs.length === 0) {
    throw new Error('Design JSON does not contain graphs[]')
  }

  const graphEntries = rawGraphs.map((raw) => {
    const symbol = graphSymbol(raw)
    const ops = raw.ops ?? []
    const vals = raw.vals ?? []
    const ports = raw.ports ?? {}
    const instances = ops
      .filter((op) => op.kind === 'kInstance' || op.kind === 'kBlackbox')
      .map((op) => ({
        moduleName: attrAsString(op.attrs, 'moduleName') ?? '<unknown-module>',
        instanceName:
          (attrAsString(op.attrs, 'instanceName') ?? op.sym.replace(/^_+/, '')) || op.sym,
      }))
    const kindCounts = new Map<string, number>()
    for (const op of ops) {
      kindCounts.set(op.kind, (kindCounts.get(op.kind) ?? 0) + 1)
    }
    const topKinds = [...kindCounts.entries()]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, 4)
      .map(([kind]) => kind)
    const summary: GraphSummary = {
      symbol,
      opCount: ops.length,
      valueCount: vals.length,
      portCount:
        (ports.in?.length ?? 0) +
        (ports.out?.length ?? 0) +
        (ports.inout?.length ?? 0),
      instanceCount: instances.length,
      children: [...new Set(instances.map((item) => item.moduleName))],
      topKinds,
    }
    return {
      symbol,
      raw,
      summary,
      instances,
    }
  })

  const graphsBySymbol = new Map(graphEntries.map((entry) => [entry.symbol, entry]))
  const tops = payload.tops?.length ? payload.tops : [graphEntries[0].symbol]

  function expandHierarchy(
    symbol: string,
    path: string,
    ancestors: Set<string>,
    instanceName: string | null,
  ): HierarchyNode {
    const entry = graphsBySymbol.get(symbol)
    const children = entry
      ? entry.instances.map((instance, index) => {
          const childPath = `${path}/${instance.instanceName}:${instance.moduleName}:${index}`
          if (ancestors.has(instance.moduleName)) {
            return {
              id: childPath,
              label: instance.instanceName,
              path: childPath,
              graphSymbol: instance.moduleName,
              moduleName: instance.moduleName,
              instanceName: instance.instanceName,
              children: [],
            }
          }
          const nextAncestors = new Set(ancestors)
          nextAncestors.add(instance.moduleName)
          return expandHierarchy(
            instance.moduleName,
            childPath,
            nextAncestors,
            instance.instanceName,
          )
        })
      : []

    return {
      id: path,
      label: instanceName ?? symbol,
      path,
      graphSymbol: symbol,
      moduleName: symbol,
      instanceName,
      children,
    }
  }

  const tree = tops.map((top) => expandHierarchy(top, top, new Set([top]), top))
  const overview: DesignOverview = {
    summary: {
      graphCount: graphEntries.length,
      operationCount: graphEntries.reduce((sum, entry) => sum + entry.summary.opCount, 0),
      valueCount: graphEntries.reduce((sum, entry) => sum + entry.summary.valueCount, 0),
      portCount: graphEntries.reduce((sum, entry) => sum + entry.summary.portCount, 0),
      instanceCount: graphEntries.reduce((sum, entry) => sum + entry.summary.instanceCount, 0),
    },
    graphs: graphEntries
      .map((entry) => entry.summary)
      .sort((left, right) => left.symbol.localeCompare(right.symbol)),
    tree,
    tops,
  }

  return {
    overview,
    graphsBySymbol,
  }
}

function buildGraphDetail(symbol: string, instancePath: string | undefined): GraphDetail {
  if (!currentDesign) {
    throw new Error('No design is loaded yet')
  }
  const entry = currentDesign.graphsBySymbol.get(symbol)
  if (!entry) {
    throw new Error(`Graph not found: ${symbol}`)
  }
  const graph = entry.raw
  const ports = graph.ports ?? {}
  const inputPorts = ports.in ?? []
  const outputPorts = ports.out ?? []
  const inoutPorts = ports.inout ?? []
  const vals = graph.vals ?? []
  const ops = graph.ops ?? []
  const valueBySymbol = new Map(vals.map((value) => [value.sym, value]))
  const opIndexBySymbol = new Map(ops.map((op, index) => [op.sym, index]))
  const inputPortByValue = new Map(inputPorts.map((port) => [port.val, port.name]))
  const inoutInByValue = new Map(inoutPorts.map((port) => [port.in, port.name]))

  const incomingForward = Array.from({ length: ops.length }, () => new Set<number>())
  const forwardEdges: Array<{ source: number; target: number; weight: number }> = []
  const backEdges: Array<{ source: number; target: number; weight: number }> = []
  const portEdges: Array<{ sourceValue: string; target: number; weight: number }> = []

  for (let target = 0; target < ops.length; target += 1) {
    const op = ops[target]
    for (const inputValue of op.in ?? []) {
      const value = valueBySymbol.get(inputValue)
      const width = value?.w ?? 1
      const sourceOp = value?.def ? opIndexBySymbol.get(value.def) : undefined
      if (sourceOp !== undefined) {
        if (sourceOp < target) {
          incomingForward[target].add(sourceOp)
          forwardEdges.push({ source: sourceOp, target, weight: width })
        } else {
          backEdges.push({ source: sourceOp, target, weight: width })
        }
      } else if (inputPortByValue.has(inputValue) || inoutInByValue.has(inputValue)) {
        portEdges.push({ sourceValue: inputValue, target, weight: width })
      }
    }
  }

  const layers = new Array<number>(ops.length).fill(1)
  for (let index = 0; index < ops.length; index += 1) {
    let layer = 1
    for (const source of incomingForward[index]) {
      layer = Math.max(layer, layers[source] + 1)
    }
    layers[index] = layer
  }
  const opMaxLayer = layers.reduce((max, current) => Math.max(max, current), 1)
  const outputLayer = opMaxLayer + 1

  const nodesByLayer = new Map<number, SchematicNode[]>()
  const pushNode = (layer: number, node: SchematicNode) => {
    const bucket = nodesByLayer.get(layer)
    if (bucket) {
      bucket.push(node)
      return
    }
    nodesByLayer.set(layer, [node])
  }

  for (const port of inputPorts) {
    pushNode(0, {
      id: `port:in:${port.name}`,
      label: port.name,
      secondaryLabel: port.val,
      kind: 'input-port',
      role: 'port-in',
      layer: 0,
      x: 0,
      y: 0,
      width: 160,
      height: 38,
      inputs: [],
      outputs: [port.val],
      attrs: [],
    })
  }
  for (const port of inoutPorts) {
    pushNode(0, {
      id: `port:inout:${port.name}`,
      label: port.name,
      secondaryLabel: `${port.in} / ${port.out}`,
      kind: 'inout-port',
      role: 'port-inout',
      layer: 0,
      x: 0,
      y: 0,
      width: 180,
      height: 42,
      inputs: [port.in],
      outputs: [port.out],
      attrs: port.oe ? [['oe', port.oe]] : [],
    })
  }

  for (let index = 0; index < ops.length; index += 1) {
    const op = ops[index]
    const attrs: Array<[string, string]> = Object.entries(op.attrs ?? {}).map(
      ([key, payload]) => [key, attrPayloadToString(payload)] as [string, string],
    )
    const secondaryLabel =
      attrAsString(op.attrs, 'moduleName') ??
      attrAsString(op.attrs, 'instanceName') ??
      null
    const label = op.kind === 'kInstance' ? secondaryLabel ?? op.sym : op.sym
    const width = Math.min(240, Math.max(132, 74 + label.length * 7))
    pushNode(layers[index], {
      id: op.sym,
      label,
      secondaryLabel,
      kind: op.kind,
      role: 'op',
      layer: layers[index],
      x: 0,
      y: 0,
      width,
      height: secondaryLabel ? 54 : 40,
      inputs: op.in ?? [],
      outputs: op.out ?? [],
      attrs,
    })
  }

  for (const port of outputPorts) {
    pushNode(outputLayer, {
      id: `port:out:${port.name}`,
      label: port.name,
      secondaryLabel: port.val,
      kind: 'output-port',
      role: 'port-out',
      layer: outputLayer,
      x: 0,
      y: 0,
      width: 160,
      height: 38,
      inputs: [port.val],
      outputs: [],
      attrs: [],
    })
  }

  const orderedLayers = [...nodesByLayer.keys()].sort((left, right) => left - right)
  const nodes: SchematicNode[] = []
  const nodeIndexById = new Map<string, number>()
  const layerBands: LayerBand[] = []
  const layerSpacing = 260
  const nodeSpacing = 70
  const leftMargin = 52
  let maxHeight = 160

  for (const layer of orderedLayers) {
    const layerNodes = nodesByLayer.get(layer) ?? []
    layerNodes.sort((left, right) => left.id.localeCompare(right.id))
    const x = leftMargin + layer * layerSpacing
    let y = 40
    for (const node of layerNodes) {
      node.x = x
      node.y = y
      nodeIndexById.set(node.id, nodes.length)
      nodes.push(node)
      y += node.height + nodeSpacing
    }
    maxHeight = Math.max(maxHeight, y)
    layerBands[layer] = {
      layer,
      x,
      centerY: y > 40 ? (40 + y - nodeSpacing) / 2 : 60,
      count: layerNodes.length,
    }
  }

  const edges: SchematicEdge[] = []

  for (const edge of forwardEdges) {
    edges.push({
      id: `f:${edge.source}:${edge.target}`,
      source: nodeIndexById.get(ops[edge.source].sym) ?? 0,
      target: nodeIndexById.get(ops[edge.target].sym) ?? 0,
      weight: edge.weight,
      kind: 'forward',
    })
  }

  for (const edge of backEdges) {
    edges.push({
      id: `b:${edge.source}:${edge.target}`,
      source: nodeIndexById.get(ops[edge.source].sym) ?? 0,
      target: nodeIndexById.get(ops[edge.target].sym) ?? 0,
      weight: edge.weight,
      kind: 'backedge',
    })
  }

  for (const edge of portEdges) {
    const portName =
      inputPortByValue.get(edge.sourceValue) ?? inoutInByValue.get(edge.sourceValue) ?? edge.sourceValue
    const sourceId = inputPortByValue.has(edge.sourceValue)
      ? `port:in:${portName}`
      : `port:inout:${portName}`
    const sourceIndex = nodeIndexById.get(sourceId)
    const targetIndex = nodeIndexById.get(ops[edge.target].sym)
    if (sourceIndex !== undefined && targetIndex !== undefined) {
      edges.push({
        id: `p:${sourceId}:${ops[edge.target].sym}`,
        source: sourceIndex,
        target: targetIndex,
        weight: edge.weight,
        kind: 'port',
      })
    }
  }

  for (const port of outputPorts) {
    const value = valueBySymbol.get(port.val)
    const sourceIndex = value?.def ? nodeIndexById.get(value.def) : undefined
    const targetIndex = nodeIndexById.get(`port:out:${port.name}`)
    const defSymbol = value?.def
    if (defSymbol && sourceIndex !== undefined && targetIndex !== undefined) {
      edges.push({
        id: `out:${defSymbol}:${port.name}`,
        source: sourceIndex,
        target: targetIndex,
        weight: value?.w ?? 1,
        kind: 'port',
      })
    }
  }

  for (const port of inoutPorts) {
    const value = valueBySymbol.get(port.out)
    const sourceIndex = value?.def ? nodeIndexById.get(value.def) : undefined
    const targetIndex = nodeIndexById.get(`port:inout:${port.name}`)
    const defSymbol = value?.def
    if (defSymbol && sourceIndex !== undefined && targetIndex !== undefined) {
      edges.push({
        id: `io:${defSymbol}:${port.name}`,
        source: sourceIndex,
        target: targetIndex,
        weight: value?.w ?? 1,
        kind: 'backedge',
      })
    }
  }

  const bundleMap = new Map<string, EdgeBundle>()
  for (const edge of edges) {
    const sourceLayer = nodes[edge.source]?.layer ?? 0
    const targetLayer = nodes[edge.target]?.layer ?? sourceLayer
    const key = `${sourceLayer}:${targetLayer}:${edge.kind}`
    const existing = bundleMap.get(key)
    if (existing) {
      existing.count += 1
      existing.weight += edge.weight
      continue
    }
    bundleMap.set(key, {
      id: key,
      fromLayer: sourceLayer,
      toLayer: targetLayer,
      count: 1,
      weight: edge.weight,
      kind: edge.kind,
    })
  }

  return {
    symbol,
    instancePath: instancePath ?? null,
    opCount: ops.length,
    valueCount: vals.length,
    portCount: inputPorts.length + outputPorts.length + inoutPorts.length,
    backedgeCount: backEdges.length,
    layerCount: orderedLayers.length,
    width: leftMargin + (outputLayer + 1) * layerSpacing,
    height: maxHeight,
    nodes,
    edges,
    bundles: [...bundleMap.values()],
    layerBands,
  }
}

self.onmessage = (event: MessageEvent<WorkerRequest>) => {
  const message = event.data
  if (message.type === 'load-design') {
    try {
      const text = new TextDecoder().decode(message.buffer)
      const payload = JSON.parse(text) as GrhDesign
      currentDesign = normalizeDesign(payload)
      const response: WorkerResponse = {
        type: 'design-loaded',
        requestId: message.requestId,
        fileName: message.fileName,
        design: currentDesign.overview,
      }
      postMessage(response)
    } catch (error) {
      const messageText = error instanceof Error ? error.message : 'Unknown parse failure'
      fail(message.requestId, 'load-design', messageText)
    }
    return
  }

  if (message.type === 'load-graph') {
    try {
      const graph = buildGraphDetail(message.symbol, message.instancePath)
      const response: WorkerResponse = {
        type: 'graph-loaded',
        requestId: message.requestId,
        graph,
      }
      postMessage(response)
    } catch (error) {
      const messageText = error instanceof Error ? error.message : 'Unknown graph build failure'
      fail(message.requestId, 'load-graph', messageText)
    }
  }
}
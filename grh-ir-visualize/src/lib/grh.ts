export type GrhScalar = boolean | number | string

export type GrhAttrPayload = {
  t?: string
  k?: string
  kind?: string
  v?: GrhScalar
  value?: GrhScalar
  vs?: GrhScalar[]
  values?: GrhScalar[]
}

export type GrhLoc = {
  file?: string
  line?: number
  col?: number
  endLine?: number
  endCol?: number
  origin?: string
  pass?: string
  note?: string
}

export type GrhValueUser = {
  op: string
  idx: number
}

export type GrhValue = {
  sym: string
  w?: number
  sgn?: boolean
  in?: boolean
  out?: boolean
  inout?: boolean
  def?: string
  users?: GrhValueUser[]
  loc?: GrhLoc
}

export type GrhPort = {
  name: string
  val: string
}

export type GrhInoutPort = {
  name: string
  in: string
  out: string
  oe?: string
}

export type GrhOperation = {
  sym: string
  kind: string
  in?: string[]
  out?: string[]
  attrs?: Record<string, GrhAttrPayload>
  loc?: GrhLoc
}

export type GrhGraph = {
  symbol?: string
  name?: string
  declaredSymbols?: string[]
  vals?: GrhValue[]
  ports?: {
    in?: GrhPort[]
    out?: GrhPort[]
    inout?: GrhInoutPort[]
  }
  ops?: GrhOperation[]
}

export type GrhDesign = {
  graphs?: GrhGraph[]
  aliases?: Record<string, string>
  declaredSymbols?: string[]
  tops?: string[]
}

export type GraphSummary = {
  symbol: string
  opCount: number
  valueCount: number
  portCount: number
  instanceCount: number
  children: string[]
  topKinds: string[]
}

export type HierarchyNode = {
  id: string
  label: string
  path: string
  graphSymbol: string
  moduleName: string
  instanceName: string | null
  children: HierarchyNode[]
}

export type DesignOverview = {
  summary: {
    graphCount: number
    operationCount: number
    valueCount: number
    portCount: number
    instanceCount: number
  }
  graphs: GraphSummary[]
  tree: HierarchyNode[]
  tops: string[]
}

export type SchematicNode = {
  id: string
  label: string
  secondaryLabel: string | null
  kind: string
  role: 'op' | 'port-in' | 'port-out' | 'port-inout'
  layer: number
  x: number
  y: number
  width: number
  height: number
  inputs: string[]
  outputs: string[]
  attrs: Array<[string, string]>
}

export type SchematicEdge = {
  id: string
  source: number
  target: number
  weight: number
  kind: 'forward' | 'backedge' | 'port'
}

export type LayerBand = {
  layer: number
  x: number
  centerY: number
  count: number
}

export type EdgeBundle = {
  id: string
  fromLayer: number
  toLayer: number
  count: number
  weight: number
  kind: 'forward' | 'backedge' | 'port'
}

export type GraphDetail = {
  symbol: string
  instancePath: string | null
  opCount: number
  valueCount: number
  portCount: number
  backedgeCount: number
  layerCount: number
  width: number
  height: number
  nodes: SchematicNode[]
  edges: SchematicEdge[]
  bundles: EdgeBundle[]
  layerBands: LayerBand[]
}

export type WorkerRequest =
  | {
      type: 'load-design'
      requestId: number
      fileName: string
      buffer: ArrayBuffer
    }
  | {
      type: 'load-graph'
      requestId: number
      symbol: string
      instancePath?: string
    }

export type WorkerResponse =
  | {
      type: 'design-loaded'
      requestId: number
      fileName: string
      design: DesignOverview
    }
  | {
      type: 'graph-loaded'
      requestId: number
      graph: GraphDetail
    }
  | {
      type: 'error'
      requestId: number
      stage: 'load-design' | 'load-graph'
      message: string
    }

export function graphSymbol(graph: GrhGraph): string {
  return graph.symbol ?? graph.name ?? '<unnamed>'
}

export function attrPayloadToString(payload: GrhAttrPayload | undefined): string {
  if (!payload) {
    return 'null'
  }
  const scalar = payload.v ?? payload.value
  if (scalar !== undefined) {
    return String(scalar)
  }
  const vector = payload.vs ?? payload.values
  if (vector) {
    return vector.join(', ')
  }
  return payload.t ?? payload.k ?? payload.kind ?? 'attr'
}

export function attrAsString(
  attrs: Record<string, GrhAttrPayload> | undefined,
  key: string,
): string | undefined {
  if (!attrs) {
    return undefined
  }
  const value = attrs[key]
  if (!value) {
    return undefined
  }
  const scalar = value.v ?? value.value
  if (scalar === undefined) {
    return undefined
  }
  return String(scalar)
}
"""Shared ordinary-GRH simulation flow; no independent model or CPU planning pass."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from grhsim_provenance import capture_generation, generated_identity, write_identity


STAGES = ("converted", "event-output-split", "nonsink-sink-split",
          "nonsink-partitioned", "sink-partitioned")

RETIRED_OPTIONS = {
    "XS_WOLF_GRHSIM_IR_COMB_PACK": "comb-pack was removed",
    "XS_WOLF_GRHSIM_IR_COMB_PACK_REPORT": "comb-pack was removed",
    "XS_WOLF_GRHSIM_IR_SELECT_STATE_STORES": "state layout is owned by the emitter",
    "XS_WOLF_GRHSIM_IR_STATE_STORE_REPORT": "use the emitter manifest",
    "XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT": "use XS_WOLF_GRHSIM_IR_MAX_TU_BYTES",
    "XS_WOLF_GRHSIM_IR_DUMP_POST_LOWER_JSON": "use XS_WOLF_GRHSIM_IR_DUMP_POST_CONVERSION_JSON",
    "GRHSIM_REEMIT_CPU_TARGET_BATCH_COUNT": "use GRHSIM_REEMIT_MAX_TU_BYTES",
    "GRHSIM_REEMIT_REMAP": "resume an ordinary GRH checkpoint",
    "GRHSIM_REEMIT_BITWISE_MUXES": "grhsim-simplify owns this optimization",
    "GRHSIM_REEMIT_MUX_CHAIN_FOLD": "grhsim-simplify owns this optimization",
    "GRHSIM_REEMIT_USED_BITS": "grhsim-simplify owns this optimization",
    "GRHSIM_REEMIT_CANONICALIZE_COMPUTE": "grhsim-simplify owns this optimization",
    "GRHSIM_REEMIT_HELPER_MAX_ESTIMATED_LINES": "use GRHSIM_REEMIT_MAX_FUNCTION_LINES",
    "GRHSIM_REEMIT_SEMANTIC_NODE_MAX_OP": "use GRHSIM_REEMIT_MAX_NODE_WORK",
    "GRHSIM_REEMIT_COARSEN_MAX_OP": "use GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE",
}


def validate_environment(environ=None) -> None:
    environ = os.environ if environ is None else environ
    retired = [f"{name}: {replacement}" for name, replacement in RETIRED_OPTIONS.items() if name in environ]
    if retired:
        raise ValueError("Retired GrhSIM options: " + "; ".join(retired))


def checked(diagnostics: list[dict], action: str) -> list[dict]:
    errors = [entry for entry in diagnostics if str(entry.get("kind", "")).lower() == "error"]
    if errors:
        raise RuntimeError(f"{action}: " + json.dumps(errors, ensure_ascii=False))
    return diagnostics


def run_pass(session, name: str, *, design: str, top: str, **options):
    start = time.perf_counter()
    diagnostics = session.run_pass(name, design=design, top=top, **options)
    checked(diagnostics, name)
    session.print_diagnostics(diagnostics, min_level="info")
    print(f"[grhsim] {name} done {round((time.perf_counter() - start) * 1000)}ms", file=sys.stderr, flush=True)
    return diagnostics


@dataclasses.dataclass
class FlowOptions:
    firrtl_node_cse: str = "gsim"
    firrtl_nodes: str = "off"
    cost_model: str = "legacy"
    fuse_leaves: bool = False
    nonsink_report: str | None = None
    pack_bit_registers: bool = True
    recover_masked_or: bool = True
    masked_or_min_terms: int = 16
    partition_simplify: bool = True
    mem_min_bytes: int = 64
    max_node_work: int = 128
    max_supernode_work: int = 128
    segment_penalty: int = 1
    semantic_nodes: bool = False
    clone_shared: bool = True
    clone_max_fanout: int = 8
    max_clones: int = 250000
    clone_lossy_compare: bool = True
    enable_guard_min_size: int = 0
    pack_report: str | None = None
    masked_or_report: str | None = None

    @classmethod
    def from_metadata(cls, metadata: dict) -> FlowOptions:
        result = cls()
        config = metadata.get("firrtl.nodeCseConfig")
        if config is not None:
            fields = config.split("/")
            if len(fields) != 5 or fields[0] != "v2" or fields[1] not in ("off", "gsim") or fields[2:] != ["5", "256", "1"]:
                raise ValueError("Unrecognized FIRRTL node CSE configuration; re-ingest the source")
            result.firrtl_node_cse = fields[1]
        if "grhsim.memMinBytes" in metadata:
            result.mem_min_bytes = int(metadata["grhsim.memMinBytes"])
        if "grhsim.nonsinkConfig" in metadata:
            fields = metadata["grhsim.nonsinkConfig"].split("/")
            if len(fields) == 13 and fields[0] == "v2" and fields[-1] == "op-hints-v1":
                result.firrtl_nodes, result.cost_model = fields[9:11]
                if result.firrtl_nodes not in ("off", "prefer", "auto") or result.cost_model not in ("legacy", "bytes") or fields[11] not in ("0", "1"):
                    raise ValueError("Unrecognized nonsink hint/cost policy")
                result.fuse_leaves = bool(int(fields[11]))
                fields = fields[1:9]
            elif len(fields) != 8:
                raise ValueError("Unrecognized grhsim.nonsinkConfig; rebuild from an earlier checkpoint")
            keys = ("max_node_work", "max_supernode_work", "segment_penalty", "semantic_nodes",
                    "clone_shared", "clone_max_fanout", "max_clones", "clone_lossy_compare")
            for key, raw in zip(keys, fields):
                setattr(result, key, bool(int(raw)) if isinstance(getattr(result, key), bool) else int(raw))
        if "grhsim.sinkConfig" in metadata:
            result.enable_guard_min_size = int(metadata["grhsim.sinkConfig"])
        return result

    def nonsink_options(self) -> dict:
        return {key: getattr(self, key) for key in (
            "max_node_work", "max_supernode_work", "segment_penalty", "semantic_nodes",
            "clone_shared", "clone_max_fanout", "max_clones", "clone_lossy_compare",
            "firrtl_nodes", "cost_model", "fuse_leaves")}


def finish_simulation_graph(session, *, design: str, top: str,
                            options: FlowOptions | None = None, checkpoint=None,
                            stop_after: str = "sink-partitioned") -> None:
    """Resume completed graph stages and always rebuild the revision-local schedule."""
    info = session.graph_metadata(design=design, top=top)
    metadata = info["metadata"]
    stage = metadata.get("grhsim.stage")
    if stage is not None and stage not in STAGES:
        raise ValueError(f"Cannot resume incomplete or unknown GRH stage: {stage!r}")
    if stop_after not in STAGES:
        raise ValueError(f"Unknown stop stage: {stop_after}")
    options = options or FlowOptions.from_metadata(metadata)
    if options.firrtl_node_cse not in ("off", "gsim"):
        raise ValueError("firrtl-node-cse must be off or gsim")
    if options.firrtl_nodes not in ("off", "prefer", "auto") or options.cost_model not in ("legacy", "bytes"):
        raise ValueError("Invalid nonsink hint/cost policy")
    has_nodes = "firrtl.nodeSchema" in metadata or "firrtl.nodeScopePolicy" in metadata
    if has_nodes:
        if metadata.get("firrtl.nodeSchema") != 2 or metadata.get("firrtl.nodeScopePolicy") != "soft-node-v2" or "firrtl.nodeInventory" not in metadata:
            raise ValueError("FIRRTL checkpoint lacks soft-node-v2 provenance; re-ingest the source")
        config = metadata.get("firrtl.nodeCseConfig")
        if config is not None:
            if config != f"v2/{options.firrtl_node_cse}/5/256/1" or metadata.get("firrtl.nodeOptimization") != "gsim-soft-v2":
                raise ValueError("FIRRTL node CSE checkpoint policy/configuration differs")
        elif stage is not None and stage != "converted":
            raise ValueError("FIRRTL checkpoint passed node CSE without policy evidence; re-ingest the source")
    if stage is not None and STAGES.index(stage) > STAGES.index(stop_after):
        raise ValueError("Checkpoint has already passed the requested stop stage")
    if stage in ("nonsink-partitioned", "sink-partitioned"):
        restored = FlowOptions.from_metadata(metadata)
        if options.nonsink_options() != restored.nonsink_options():
            raise ValueError("Changed activity configuration requires the nonsink-sink-split checkpoint")
        if not metadata["grhsim.nonsinkConfig"].startswith("v2/"):
            raise ValueError("Legacy nonsink checkpoint: rebuild from nonsink-sink-split")

    def run(name, **kwargs):
        return run_pass(session, name, design=design, top=top, **kwargs)

    def saved():
        if checkpoint:
            checkpoint(session.graph_metadata(design=design, top=top)["metadata"]["grhsim.stage"])

    if stage is None:
        run("grh-to-grhsim", logic_domain="2state")
        stage = "converted"
        saved()
    if stage == "converted" and (not has_nodes or "firrtl.nodeCseConfig" not in metadata):
        run("grhsim-simplify")
        if options.pack_bit_registers:
            run("grhsim-pack-bit-registers", **({"report": options.pack_report} if options.pack_report else {}))
            run("grhsim-simplify")
        if options.recover_masked_or:
            run("grhsim-recover-masked-or", min_terms=options.masked_or_min_terms,
                **({"report": options.masked_or_report} if options.masked_or_report else {}))
            run("grhsim-simplify")
        if has_nodes:
            run("grhsim-node-cse", firrtl_node_cse=options.firrtl_node_cse)
        saved()
    if stage == "converted":
        if stop_after == stage:
            return
        run("grhsim-split-event-and-output")
        stage = "event-output-split"
        saved()
    if stage == "event-output-split":
        if stop_after == stage:
            return
        run("grhsim-split-nonsink-and-sink", mem_min_bytes=options.mem_min_bytes)
        stage = "nonsink-sink-split"
        saved()
    if stage == "nonsink-sink-split":
        if stop_after == stage:
            return
        run("grhsim-partition-nonsink", **options.nonsink_options(),
            **({"report": options.nonsink_report} if options.nonsink_report else {}))
        stage = "nonsink-partitioned"
        if options.partition_simplify:
            run("grhsim-simplify")
        saved()
    if stage == "nonsink-partitioned":
        if stop_after == stage:
            return
    # Running this on an already completed checkpoint validates its stored
    # configuration and reconstructs SinkSchedule in the current session.
    run("grhsim-partition-sink", enable_guard_min_size=options.enable_guard_min_size)
    saved()


def emit_cpp(session, *, design: str, top: str, output: Path, overwrite: bool = False,
             generation_identity=None, **options) -> None:
    """Generate a replacement fully before moving the previous model aside."""
    output = output.resolve()
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        raise ValueError(f"CPU output must be a directory: {output}")
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise ValueError(f"CPU output directory is not empty: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}.generated-", dir=output.parent))
    backup = candidate.with_name(candidate.name + ".previous")
    try:
        identity = generation_identity if generation_identity is not None else capture_generation("api-emit")
        checked(session.emit_grhsim_cpu_st_cpp(design=design, top=[top], output=str(candidate), **options), "emit grhsim-cpu-st-cpp")
        write_identity(candidate / "generation-identity.json", {
            **identity, "emit": {"top": top, "options": options},
            "firrtl_node_policy": {key: value for key, value in
                session.graph_metadata(design=design, top=top)["metadata"].items()
                if key in ("firrtl.nodeSchema", "firrtl.nodeScopePolicy", "firrtl.nodeOptimization", "firrtl.nodeCseConfig",
                           "grhsim.nonsinkConfig", "grhsim.nonsinkHintStats")},
            "generated": generated_identity(candidate)})
        if output.exists():
            os.rename(output, backup)
        try:
            os.rename(candidate, output)
        except BaseException:
            if backup.exists():
                os.rename(backup, output)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if candidate.exists():
            shutil.rmtree(candidate)


def store_checkpoint(session, path: Path, *, design: str, top: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked(session.store_json(design=design, top=[top], output=str(path)), f"store {path}")

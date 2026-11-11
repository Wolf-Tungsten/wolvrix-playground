"""Shared ordinary-GRH simulation flow; no independent model or CPU planning pass."""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path

from grhsim_provenance import capture_generation, generated_identity, write_identity


# F24 names describe the operation rather than its implementation family.
# Keep the old spellings as a fallback so a frozen Python extension can still
# replay an existing checkpoint while a freshly built extension advertises the
# canonical names.
PASS_NAME_ALIASES = {
    "grhsim-dialect-translate": "grh-to-grhsim",
    "split-event-and-output": "grhsim-split-event-and-output",
    "split-nonsink-and-sink": "grhsim-split-nonsink-and-sink",
    "partition-nonsink": "grhsim-partition-nonsink",
    "partition-sink": "grhsim-partition-sink",
    "comm-expr": "common-expr",
}


_STAGE_JOURNAL_SCOPE = ContextVar("grhsim_stage_journal_scope", default="pipeline")


@contextmanager
def stage_journal_scope(scope: str):
    """Keep verification and replay work separate from the production stages."""
    token = _STAGE_JOURNAL_SCOPE.set(scope)
    try:
        yield
    finally:
        _STAGE_JOURNAL_SCOPE.reset(token)


def _stage_log_path() -> Path | None:
    """Return the optional JSONL stage journal configured by the caller.

    The production XiangShan Make target sets ``XS_FIRRTL_STAGE_LOG``.  Keeping
    the journal opt-in avoids adding filesystem work to the small fixture and
    unit-test flows while still making every long-running stage auditable in a
    full-chip run.
    """
    raw = os.environ.get("XS_FIRRTL_STAGE_LOG", "").strip()
    return Path(raw).resolve() if raw else None


def record_stage_event(stage: str, event: str, *, elapsed_s: float | None = None,
                       detail: str | None = None) -> None:
    """Append one stage lifecycle event to the configured JSONL journal.

    Journal failures are deliberately non-fatal: a diagnostic record must not
    change the simulation graph or hide the actual pass error.  The parent
    directory is created lazily so a caller can point the journal into its
    per-run ``ptmp`` evidence directory.
    """
    path = _stage_log_path()
    if path is None:
        return
    row = {"scope": _STAGE_JOURNAL_SCOPE.get(), "stage": stage,
           "event": event, "time": time.time()}
    if elapsed_s is not None:
        row["elapsed_s"] = elapsed_s
    if detail:
        row["detail"] = detail
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # Evidence collection is best effort.  Preserve the original workflow
        # error and keep the normal no-journal path allocation-free.
        return


STAGES = ("converted", "event-output-split", "nonsink-sink-split",
          "nonsink-partitioned", "sink-partitioned")

RETIRED_OPTIONS = {
    "XS_GRHSIM_SEMANTIC_NODE_MAX_OP": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_GRHSIM_COARSEN_MAX_OP": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_GRHSIM_MAX_NODE_WORK": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_GRHSIM_MAX_SUPERNODE_WORK": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_GRHSIM_FUSE_LEAVES": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_GRHSIM_SIMPLIFY": "grhsim-simplify was removed; use the canonical optimization stages",
    "XS_GRHSIM_SIMPLIFY_MAX_ROUNDS": "grhsim-simplify was removed; canonical optimization stages do not accept simplify rounds",
    "XS_GRHSIM_PHASE_SIMPLIFY": "partition-local simplify was removed; use the canonical optimization stages",
    "XS_GRHSIM_MASKED_OR": "recover-masked-or was removed; use pattern-detect",
    "XS_GRHSIM_MASKED_OR_MIN_TERMS": "recover-masked-or was removed; use pattern-detect",
    "XS_GRHSIM_MASKED_OR_REPORT": "recover-masked-or was removed; inspect canonical stage checkpoints",
    "XS_GRHSIM_FIRRTL_NODE_CSE": "node-cse was removed; use comm-expr",
    "XS_GRHSIM_PACK_BIT_REGISTERS": "pack-bit-registers was removed; state layout is owned by the emitter",
    "XS_GRHSIM_PACK_BIT_REGISTERS_REPORT": "pack-bit-registers was removed; use the emitter manifest",
    "XS_GRHSIM_DUMP_PRE_SIMPLIFY_JSON": "use explicit SV --dump-pre-simplify-json; canonical FIRRTL has no simplify stage",
    "GRHSIM_REEMIT_MAX_NODE_WORK": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "GRHSIM_REEMIT_MAX_SUPERNODE_WORK": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "GRHSIM_REEMIT_FUSE_LEAVES": "use max-supernode-nodes with an explicit node count; rebuild from nonsink-sink-split",
    "XS_WOLF_GRHSIM_IR_COMB_PACK": "comb-pack was removed",
    "XS_WOLF_GRHSIM_IR_COMB_PACK_REPORT": "comb-pack was removed",
    "XS_WOLF_GRHSIM_IR_SELECT_STATE_STORES": "state layout is owned by the emitter",
    "XS_WOLF_GRHSIM_IR_STATE_STORE_REPORT": "use the emitter manifest",
    "XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT": "use XS_WOLF_GRHSIM_IR_MAX_TU_BYTES",
    "XS_WOLF_GRHSIM_IR_DUMP_POST_LOWER_JSON": "use XS_WOLF_GRHSIM_IR_DUMP_POST_CONVERSION_JSON",
    "GRHSIM_REEMIT_CPU_TARGET_BATCH_COUNT": "use GRHSIM_REEMIT_MAX_TU_BYTES",
    "GRHSIM_REEMIT_REMAP": "resume an ordinary GRH checkpoint",
    "GRHSIM_REEMIT_USED_BITS": "use the integrated used-bits stage",
    "GRHSIM_REEMIT_HELPER_MAX_ESTIMATED_LINES": "use GRHSIM_REEMIT_MAX_FUNCTION_LINES",
    "GRHSIM_REEMIT_SEMANTIC_NODE_MAX_OP": "use GRHSIM_REEMIT_MAX_SUPERNODE_NODES (node count)",
    "GRHSIM_REEMIT_COARSEN_MAX_OP": "use GRHSIM_REEMIT_MAX_SUPERNODE_NODES (node count)",
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


def _run_named_pass(session, name: str, pass_kwargs: dict):
    """Run a canonical pass, falling back only for an unknown legacy build."""
    legacy = PASS_NAME_ALIASES.get(name)
    candidates = (name, legacy) if legacy else (name,)
    for candidate in candidates:
        try:
            diagnostics = session.run_pass(candidate, **pass_kwargs)
        except (RuntimeError, ValueError, TypeError) as error:
            message = str(error).lower()
            if candidate != candidates[-1] and ("unknown pass" in message or
                                                "does not accept named" in message):
                continue
            raise
        unknown = any(
            str(entry.get("kind", "")).lower() == "error" and
            "unknown pass" in str(entry.get("message", "")).lower()
            for entry in diagnostics
            if isinstance(entry, dict)
        )
        if not unknown or candidate == candidates[-1]:
            return diagnostics
    raise AssertionError("unreachable pass alias fallback")


def run_pass(session, name: str, *, design: str, top: str | None = None, **options):
    start = time.perf_counter()
    print(f"[grhsim] {name} start", file=sys.stderr, flush=True)
    record_stage_event(name, "start")
    try:
        pass_kwargs = {"design": design, **options}
        if top is not None:
            pass_kwargs["top"] = top
        diagnostics = _run_named_pass(session, name, pass_kwargs)
        checked(diagnostics, name)
        session.print_diagnostics(diagnostics, min_level="info")
    except BaseException as error:
        elapsed = time.perf_counter() - start
        record_stage_event(name, "failed", elapsed_s=elapsed, detail=str(error))
        raise
    elapsed = time.perf_counter() - start
    record_stage_event(name, "done", elapsed_s=elapsed)
    print(f"[grhsim] {name} done {round(elapsed * 1000)}ms", file=sys.stderr, flush=True)
    return diagnostics


@dataclasses.dataclass
class FlowOptions:
    firrtl_nodes: str = "auto"
    cost_model: str = "legacy"
    nonsink_report: str | None = None
    mem_min_bytes: int = 64
    max_supernode_nodes: int = 128
    segment_penalty: int = 1
    semantic_nodes: bool = False
    clone_shared: bool = True
    clone_max_fanout: int = 8
    max_clones: int = 250000
    clone_lossy_compare: bool = True
    enable_guard_min_size: int = 0

    @classmethod
    def from_metadata(cls, metadata: dict) -> FlowOptions:
        result = cls()
        if "grhsim.memMinBytes" in metadata:
            result.mem_min_bytes = int(metadata["grhsim.memMinBytes"])
        if "grhsim.nonsinkConfig" in metadata:
            fields = metadata["grhsim.nonsinkConfig"].split("/")
            if len(fields) != 11 or fields[0] != "v4" or fields[-1] != "semantic-tree-mffc-v1":
                raise ValueError("Legacy nonsink checkpoint: rebuild from nonsink-sink-split; "
                                 "SemanticTree node ownership requires v4/semantic-tree-mffc-v1")
            result.firrtl_nodes, result.cost_model = fields[8:10]
            if result.firrtl_nodes not in ("off", "prefer", "auto") or result.cost_model not in ("legacy", "bytes"):
                raise ValueError("Unrecognized nonsink hint/cost policy")
            keys = ("max_supernode_nodes", "segment_penalty", "semantic_nodes",
                    "clone_shared", "clone_max_fanout", "max_clones", "clone_lossy_compare")
            for key, raw in zip(keys, fields[1:8]):
                if isinstance(getattr(result, key), bool) and raw not in ("0", "1"):
                    raise ValueError("Invalid nonsink boolean configuration")
                value = int(raw)
                if not 0 <= value <= 2**32 - 1:
                    raise ValueError("Invalid nonsink integer configuration")
                setattr(result, key, bool(value) if isinstance(getattr(result, key), bool) else value)
            if not result.max_supernode_nodes or not result.clone_max_fanout:
                raise ValueError("Node capacity and fanout must be positive")
        if "grhsim.sinkConfig" in metadata:
            result.enable_guard_min_size = int(metadata["grhsim.sinkConfig"])
        return result

    def nonsink_options(self) -> dict:
        return {key: getattr(self, key) for key in (
            "max_supernode_nodes", "segment_penalty", "semantic_nodes",
            "clone_shared", "clone_max_fanout", "max_clones", "clone_lossy_compare",
            "firrtl_nodes", "cost_model")}


def finish_simulation_graph(session, *, design: str, top: str,
                            options: FlowOptions | None = None, checkpoint=None,
                            stop_after: str = "sink-partitioned",
                            preprocessed: bool = False) -> None:
    """Resume completed graph stages and always rebuild the revision-local schedule."""
    info = session.graph_metadata(design=design, top=top)
    metadata = info["metadata"]
    stage = metadata.get("grhsim.stage")
    if stage is not None and stage not in STAGES:
        raise ValueError(f"Cannot resume incomplete or unknown GRH stage: {stage!r}")
    if stop_after not in STAGES:
        raise ValueError(f"Unknown stop stage: {stop_after}")
    options = options or FlowOptions.from_metadata(metadata)
    if options.firrtl_nodes not in ("off", "prefer", "auto") or options.cost_model not in ("legacy", "bytes"):
        raise ValueError("Invalid nonsink hint/cost policy")
    has_nodes = "firrtl.nodeSchema" in metadata or "firrtl.nodeScopePolicy" in metadata
    if has_nodes:
        if metadata.get("firrtl.nodeSchema") != 2 or metadata.get("firrtl.nodeScopePolicy") != "soft-node-v2" or "firrtl.nodeInventory" not in metadata:
            raise ValueError("FIRRTL checkpoint lacks soft-node-v2 provenance; re-ingest the source")
    if stage is not None and STAGES.index(stage) > STAGES.index(stop_after):
        raise ValueError("Checkpoint has already passed the requested stop stage")
    if stage in ("nonsink-partitioned", "sink-partitioned"):
        restored = FlowOptions.from_metadata(metadata)
        if options.nonsink_options() != restored.nonsink_options():
            raise ValueError("Changed activity configuration requires the nonsink-sink-split checkpoint")
        if not metadata["grhsim.nonsinkConfig"].startswith("v4/"):
            raise ValueError("Legacy nonsink checkpoint: rebuild from nonsink-sink-split")

    def run(name, **kwargs):
        # DCE and the whole-graph F22/F23 passes have no -top parameter;
        # partitioned simulation passes are graph-selectable.
        if name in {"dead-code-elim", "expr-opt", "used-bits", "split-nodes", "constant-analysis",
                    "alias-analysis", "pattern-detect", "common-expr", "comm-expr"}:
            return run_pass(session, name, design=design, **kwargs)
        return run_pass(session, name, design=design, top=top, **kwargs)

    def saved():
        if checkpoint:
            checkpoint(session.graph_metadata(design=design, top=top)["metadata"]["grhsim.stage"])

    if stage is None and not preprocessed:
        # GSIM's F22/F23 passes operate on the ordinary GRH node graph. Keep
        # every liveness boundary explicit: DCE is a separate user-visible
        # pass around expression cleanup, used-bit narrowing, node splitting,
        # and constant propagation before lowering to GrhSIM.
        run("dead-code-elim", keep_declared_symbols=False)
        run("expr-opt")
        run("used-bits")
        run("split-nodes")
        # SplitNodes creates slice-specific producers and leaves complete
        # reachability cleanup to the caller, matching GSIM's RemoveDeadNodes1
        # boundary.
        run("dead-code-elim", keep_declared_symbols=False)
        run("constant-analysis")
        run("dead-code-elim", keep_declared_symbols=False)
        run("alias-analysis")
        run("pattern-detect")
        run("comm-expr")
        run("dead-code-elim", keep_declared_symbols=False)
        run("grhsim-dialect-translate", logic_domain="2state")
        stage = "converted"
    elif stage is None and preprocessed:
        # F24 executes the complete ordinary-GRH prefix explicitly so its
        # stage journal matches ingest-firrtl → ... → comm-expr.  Conversion
        # is still owned by this shared tail and establishes the checkpoint
        # stage used by restart and round-trip verification.
        run("grhsim-dialect-translate", logic_domain="2state")
        stage = "converted"
    if stage == "converted":
        saved()
        if stop_after == stage:
            return
        run("split-event-and-output")
        stage = "event-output-split"
        saved()
    if stage == "event-output-split":
        if stop_after == stage:
            return
        run("split-nonsink-and-sink", mem_min_bytes=options.mem_min_bytes)
        stage = "nonsink-sink-split"
        saved()
    if stage == "nonsink-sink-split":
        if stop_after == stage:
            return
        run("partition-nonsink", **options.nonsink_options(),
            **({"report": options.nonsink_report} if options.nonsink_report else {}))
        stage = "nonsink-partitioned"
        saved()
    if stage == "nonsink-partitioned":
        if stop_after == stage:
            return
    # Running this on an already completed checkpoint validates its stored
    # configuration and reconstructs SinkSchedule in the current session.
    run("partition-sink", enable_guard_min_size=options.enable_guard_min_size)
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
                if key in ("firrtl.nodeSchema", "firrtl.nodeScopePolicy", "firrtl.nodeOptimization",
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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    print(f"[grhsim] store checkpoint {path} start", file=sys.stderr, flush=True)
    pending = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    os.close(descriptor)
    try:
        checked(session.store_json(design=design, top=[top], mode="pretty-compact", output=str(pending)),
                f"store {path}")
        size = pending.stat().st_size
        if not size:
            raise RuntimeError(f"store {path}: empty checkpoint")
        if path.exists():
            pending.chmod(stat.S_IMODE(path.stat().st_mode))
        pending.replace(path)
        print(f"[grhsim] store checkpoint {path} done {round((time.perf_counter() - start) * 1000)}ms bytes={size}",
              file=sys.stderr, flush=True)
    finally:
        pending.unlink(missing_ok=True)

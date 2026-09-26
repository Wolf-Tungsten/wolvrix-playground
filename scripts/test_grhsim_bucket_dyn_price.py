#!/usr/bin/env python3
"""Unit tests for grhsim_bucket_dyn_price (NO00021)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_bucket_dyn_price import (  # noqa: E402
    OTHER_BUCKET,
    bucket_of_module,
    attribute_op_modules,
    classify_residence,
    compute_exec_metrics,
    monitored_by_bucket,
    parse_vchg_and_commit,
    residence_counts,
    static_bucket_counts,
    wakes_by_bucket,
)


def make_model(strings, states, values, operations, inputs=None, outputs=None):
    return {
        "strings": strings,
        "types": [[1, 0, "logic", 1, 0, "2-state", 0, 0]],
        "states": states,
        "values": values,
        "operations": operations,
        "inputs": inputs or [],
        "outputs": outputs or [],
    }


class TestBucketOfModule(unittest.TestCase):
    def test_bucket_labels(self):
        self.assertEqual(bucket_of_module("(reg-to-mem)"), "(reg-to-mem)")
        self.assertEqual(bucket_of_module("(packed)"), "(packed)")
        self.assertEqual(bucket_of_module("(events)"), "(events)")
        self.assertEqual(bucket_of_module("cpu_l_soc"), OTHER_BUCKET)
        self.assertEqual(bucket_of_module("(anonymous)"), OTHER_BUCKET)
        self.assertEqual(bucket_of_module("(mixed)"), OTHER_BUCKET)


class TestAttributeOpModules(unittest.TestCase):
    def model_fixture(self):
        strings = [
            "core.compute.and",      # 1
            "core.state.regWrite",   # 2
            "core.state.read",       # 3
            "packed_bits_12",        # 4
            "__reg_to_mem_7",        # 5
            "__event_9_0",           # 6
            "cpu$l_soc$foo",         # 7
            "_val_2",                # 8
            "logic",                 # 9
        ]
        states = [
            [1, 4, 1],   # packed_bits_12
            [2, 5, 1],   # __reg_to_mem_7
            [3, 6, 1],   # __event_9_0
            [4, 7, 1],   # cpu$l_soc$foo
        ]
        values = [
            [1, 1, 4],   # named packed_bits_12
            [2, 1, 8],   # _val_2 (generated)
            [3, 1, 6],   # named __event_9_0
            [4, 1, 7],   # named cpu$l_soc$foo
            [5, 1, 0],   # unnamed
        ]
        operations = [
            # op 1: state.read of packed_bits_12 -> result inherits (packed)
            # via the state-read naming rule (packed_bits_* value names are
            # classified generated, so attribution flows through the ref)
            [1, 3, 0, 0, [], [1], [["state", 1]]],
            # op 2: result-less regWrite to __reg_to_mem_7 -> (reg-to-mem)
            [2, 2, 0, 0, [4, 1], [], [["state", 2]]],
            # op 3: produces _val_2, consumed by op 4 (event-named) -> (events)
            [3, 1, 0, 0, [1], [2], []],
            # op 4: named __event_9_0 result -> (events)
            [4, 1, 0, 0, [2], [3], []],
            # op 5: named cpu$l_soc$foo result -> (other)
            [5, 1, 0, 0, [3], [4], []],
            # op 6: state.read of packed_bits_12, unnamed result -> result
            # inherits (packed) through the state ref naming rule
            [6, 3, 0, 0, [], [5], [["state", 1]]],
        ]
        return make_model(strings, states, values, operations)

    def test_named_result_bucket(self):
        op_module, _vnm, _owner, _aux = attribute_op_modules(self.model_fixture())
        self.assertEqual(op_module[1], "(packed)")

    def test_sink_state_ref_bucket(self):
        op_module, _vnm, _owner, _aux = attribute_op_modules(self.model_fixture())
        self.assertEqual(op_module[2], "(reg-to-mem)")

    def test_owner_propagation_bucket(self):
        op_module, _vnm, owner, _aux = attribute_op_modules(self.model_fixture())
        self.assertEqual(owner[2], "(events)")
        self.assertEqual(op_module[3], "(events)")

    def test_plain_module_is_other(self):
        op_module, _vnm, _owner, _aux = attribute_op_modules(self.model_fixture())
        self.assertEqual(op_module[5], "cpu_l_soc")

    def test_state_read_result_naming(self):
        op_module, vnm, _owner, _aux = attribute_op_modules(self.model_fixture())
        self.assertEqual(vnm[5], "(packed)")
        self.assertEqual(op_module[6], "(packed)")

    def test_every_op_attributed(self):
        op_module, _vnm, _owner, aux = attribute_op_modules(self.model_fixture())
        for pos in range(1, aux["n_ops"] + 1):
            self.assertIsNotNone(op_module[pos])


def make_mapping_model(schedule):
    payload = [0, 0, 0, 0, schedule]
    return {"mappings": [[payload]]}


class TestClassifyResidence(unittest.TestCase):
    def fixture(self):
        # partitions: [id, ?, kind, ?, children, ops]; task -> word -> unit
        partitions = {
            10: [10, 0, 0, 0, [11], []],          # task root partition
            11: [11, 0, 0, 0, [12], []],          # word partition
            12: [12, 0, 3, 0, [], [1, 2]],        # unit supernode, ops 1-2
            20: [20, 0, 0, 0, [21], []],          # commit root
            21: [21, 0, 0, 0, [], [3]],           # commit child, op 3
        }
        schedule = [[
            [0, [
                [0, [
                    [100, 10, 0, 0],   # compute task -> root 10
                    [200, 20, 0, 1],   # commit task -> root 20
                ]],
            ]],
        ]]
        view = {"partitions": partitions, "unit_ops": {12: [1, 2]}}
        return make_mapping_model(schedule), view

    def test_compute_commit_detached(self):
        model, view = self.fixture()
        info = classify_residence(model, view)
        self.assertEqual(info["residence"][1], ("compute", 12))
        self.assertEqual(info["residence"][2], ("compute", 12))
        self.assertEqual(info["residence"][3], ("commit", 200))
        self.assertNotIn(4, info["residence"])
        self.assertEqual(info["compute_units"], {12})
        self.assertEqual(info["all_task_ids"], [100, 200])

    def test_compute_wins_over_commit(self):
        model, view = self.fixture()
        # Put op 1 under the commit subtree as well; compute must win.
        view["partitions"][21][5].append(1)
        info = classify_residence(model, view)
        self.assertEqual(info["residence"][1], ("compute", 12))


class TestExecMetrics(unittest.TestCase):
    def test_join_and_orphans(self):
        view = {"unit_ops": {11: [1, 2], 12: [3]}}
        aux = {"op_kind": ["", "core.compute.and", "core.compute.and",
                           "core.state.memRead"]}
        op_bucket = ["", "(packed)", "(other)", "(reg-to-mem)"]
        info = {"compute_units": {11, 12}}
        body = {11: 10, 12: 5, 99: 7}
        metrics = compute_exec_metrics(view, aux, op_bucket, info, body)
        self.assertEqual(metrics["per_bucket"]["(packed)"], 10)
        self.assertEqual(metrics["per_bucket"]["(other)"], 10)
        self.assertEqual(metrics["per_bucket"]["(reg-to-mem)"], 5)
        self.assertEqual(metrics["total"], 25)
        self.assertEqual(metrics["orphan_sn_units"], [99])
        self.assertEqual(metrics["missing_units"], [])
        self.assertEqual(metrics["silent_units"], [])
        self.assertEqual(
            metrics["per_bucket_kind"][("(packed)", "core.compute.and")], 10)
        self.assertEqual(
            metrics["per_bucket_kind"][("(reg-to-mem)", "core.state.memRead")], 5)

    def test_silent_units(self):
        view = {"unit_ops": {11: [1]}}
        aux = {"op_kind": ["", "core.compute.and"]}
        op_bucket = ["", "(events)"]
        info = {"compute_units": {11, 13}}
        metrics = compute_exec_metrics(view, aux, op_bucket, info, {11: 3})
        self.assertEqual(metrics["silent_units"], [13])
        self.assertEqual(metrics["total"], 3)


class TestMonitoredByBucket(unittest.TestCase):
    def test_bucketed_aggregates(self):
        value_named_module = [None, "(packed)", None, None]
        owner = [None, "(packed)", "(reg-to-mem)", "cpu_l_soc"]
        vchg = {1: (5, 1), 2: (7, 2), 3: (3, 0)}
        buckets, total_wr, total_ch, oor = monitored_by_bucket(
            [""] * 4, value_named_module, owner, vchg, 3)
        self.assertEqual(buckets["(packed)"], {"values": 1, "wr": 5, "ch": 1})
        self.assertEqual(buckets["(reg-to-mem)"], {"values": 1, "wr": 7, "ch": 2})
        self.assertEqual(buckets[OTHER_BUCKET], {"values": 1, "wr": 3, "ch": 0})
        self.assertEqual((total_wr, total_ch), (15, 3))
        self.assertEqual(oor, [])

    def test_named_module_wins_over_owner(self):
        value_named_module = [None, "cpu_a_b"]
        owner = [None, "(events)"]
        buckets, _tw, _tc, _oor = monitored_by_bucket(
            [""] * 2, value_named_module, owner, {1: (1, 1)}, 1)
        self.assertNotIn("(events)", buckets)
        self.assertEqual(buckets[OTHER_BUCKET], {"values": 1, "wr": 1, "ch": 1})

    def test_out_of_range(self):
        _b, _tw, _tc, oor = monitored_by_bucket(
            [""] * 2, [None, None], [None, None], {9: (1, 0)}, 1)
        self.assertEqual(oor, [9])


class TestWakesByBucket(unittest.TestCase):
    def test_wake_math(self):
        residence = {10: ("compute", 11), 11: ("compute", 12),
                     12: ("commit", 200)}
        consumers_of = {1: [10, 11], 2: [12], 3: [10, 10], 4: [999]}
        vchg = {1: (0, 2), 2: (0, 3), 3: (0, 0), 4: (0, 5)}
        bucket_of_value = {1: "(packed)", 2: "(events)",
                           3: "(other)", 4: "(other)"}.get
        per_bucket, per_bucket_commit, total = wakes_by_bucket(
            residence, consumers_of, vchg, bucket_of_value)
        self.assertEqual(per_bucket["(packed)"], 4)       # 2 x 2 units
        self.assertEqual(per_bucket_commit["(events)"], 3)  # 3 x 1 commit task
        self.assertEqual(per_bucket["(events)"], 0)
        self.assertEqual(per_bucket["(other)"], 0)         # op 999 detached
        self.assertEqual(total, 4)


class TestStaticCounts(unittest.TestCase):
    def test_static_and_residence(self):
        op_module = ["", "(packed)", "(events)", "cpu_a_b"]
        op_kind = ["", "core.compute.and", "core.state.regWrite",
                   "core.compute.add"]
        per_bucket, per_kind = static_bucket_counts(op_module, op_kind, 3)
        self.assertEqual(per_bucket["(packed)"], 1)
        self.assertEqual(per_bucket["(events)"], 1)
        self.assertEqual(per_bucket[OTHER_BUCKET], 1)
        self.assertEqual(per_kind[("(events)", "core.state.regWrite")], 1)

        op_bucket = ["", "(packed)", "(events)", "(other)"]
        residence = {1: ("compute", 11), 2: ("commit", 200)}
        counts, detached = residence_counts(residence, op_bucket, 3)
        self.assertEqual(counts[("(packed)", "compute")], 1)
        self.assertEqual(counts[("(events)", "commit")], 1)
        self.assertEqual(counts[("(other)", "detached")], 1)
        self.assertEqual(detached, [3])


class TestParseVchgAndCommit(unittest.TestCase):
    def test_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            path.write_text(
                "[grhsim-vchg] v 1 wr=101005 ch=100001\n"
                "[grhsim-dyn] sn 1008203 act=667 body=667 grp=667 chg=667\n"
                "[grhsim-vchg] v 2 wr=401257 ch=200102\n"
                "[grhsim-dyn] commit 3951 ent=200102\n"
                "[grhsim-dyn] totals grp_fire=254170299\n",
                encoding="utf-8")
            vchg, commit = parse_vchg_and_commit(path)
        self.assertEqual(vchg, {1: (101005, 100001), 2: (401257, 200102)})
        self.assertEqual(commit, {3951: 200102})


if __name__ == "__main__":
    unittest.main()

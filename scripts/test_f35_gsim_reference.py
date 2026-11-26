"""Exercise GSIM input provenance and the F35 capture/replay contract."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from benchmark_f29_pass_trace import sha256, write_json_atomic
from f35_gsim_reference import (GSIM_BUNDLES, TIMING, freeze_reference, pass_budgets,
                                resume_reference, run_gsim_reference)
from semantic_node_exchange import parsed_row, verify_bundle


FIXTURE = '''FIRRTL version 6.0.0
circuit OriginTrace :
  module Child :
    input a : UInt<1>
    output y : UInt<1>
    node n = not(a)
    connect y, n
  module OriginTrace :
    input a : UInt<1>
    output out : UInt<1>
    inst child of Child
    connect child.a, a
    connect out, child.y
    invalidate out
'''


def rows(path, select):
    with path.open() as stream:
        next(stream)
        fields = next(stream).strip().split('\t')
        return [value for line in stream if not line.startswith('#')
                and select(value := parsed_row(line, fields))]


class F35GsimReferenceTests(unittest.TestCase):
    def test_native_reference_keeps_source_keys_and_exact_stop(self):
        binary_file = os.environ.get('F35_GSIM_BINARY')
        if not binary_file:
            self.skipTest('F35_GSIM_BINARY is unset')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / 'OriginTrace.fir'
            source.write_text(FIXTURE)
            args = SimpleNamespace(binary=Path(binary_file), output=output, firrtl=source,
                                   stop_before_final_dce=False, top='OriginTrace', run_id='f35-test')
            input_sha = sha256(source)
            identity, passes = run_gsim_reference(args, input_sha)
            self.assertEqual(resume_reference(args, input_sha), (identity, passes))
            for bundle in GSIM_BUNDLES:
                write_json_atomic(output / bundle / 'verification.json', verify_bundle(output / bundle))
            summary = {'engine': 'gsim', 'binary': identity, 'passes': passes, 'verified_replay': True,
                       'inputs': {'sources': [{'path': str(source), 'sha256': input_sha}]}}
            write_json_atomic(output / 'summary.json', summary)
            manifest = freeze_reference(args, summary)
            final = manifest['files']['dce-3/after.nodes.tsv']['metadata']
            self.assertEqual((final['stage'], final['pass_instance']), ('RemoveDeadNodes3', 'RemoveDeadNodes#2'))
            self.assertEqual(len(pass_budgets(output / TIMING)), 13)
            origins = {tuple(json.loads(row['source_path_json'])): row
                       for row in rows(output / 'init-node-origins.tsv', lambda row: True)}
            self.assertEqual(origins['child', 'n']['source_line'], '6')
            self.assertEqual(origins['child', 'y']['source_line'], '5')
            scopes = rows(output / 'init-source-scopes.tsv', lambda row: row['module'] == 'Child')
            self.assertEqual([(row['module_line'], row['instance_line']) for row in scopes], [('3', '11')])
            out = origins['out',]['node_id']
            assigns = rows(output / 'init-source-assignments.tsv', lambda row: row['target_source_node_id'] == out)
            self.assertEqual([(row['source_line'], row['kind'], row['lowering']) for row in assigns],
                             [('13', 'connect', 'lowered'), ('14', 'invalidate', 'ignored-existing-driver')])

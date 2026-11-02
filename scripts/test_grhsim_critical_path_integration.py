#!/usr/bin/env python3
"""Native Slang/GRH and real Verilator checks; artifacts stay in the test tree."""
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from grhsim_source_map import ROOT, identity, source_span
from grhsim_rtl_rewrite import propose, verify
from types import SimpleNamespace

BIN = ROOT / 'build/grhsim32-tools/bin'
ARTIFACTS = ROOT / 'wolvrix/build/artifacts/grhsim-critical-path'
FIXTURES = ROOT / 'testcase/grhsim-critical-path'


class NativeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for target in ('grhsim32_rtl_rewrite', 'grhsim32_source_map_fixture', 'grhsim32_frontend'):
            if not (BIN / target).is_file():
                raise RuntimeError('Build tools/grhsim32 target ' + target + ' before running this integration suite')

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='integration-', dir=ARTIFACTS))

    def native(self, source, top='top'):
        rtl = self.root / (top + '.sv'); rtl.write_text(source)
        out = self.root / (top + '.json')
        with (self.root / (top + '.log')).open('w') as log:
            subprocess.run([str(BIN/'grhsim32_rtl_rewrite'), str(out), top, str(rtl)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        return json.loads(out.read_text())

    def test_clone_serialization_and_static_state_boundary(self):
        subprocess.run([str(BIN/'grhsim32_source_map_fixture'), str(self.root)], check=True)

    def test_ast_rejects_signed_partial_dynamic_memory_event_and_delay(self):
        result = self.native('''module top(input logic clk, input logic [7:0] a,
            input logic signed [7:0] s, input logic [1:0] idx,
            output wire [7:0] good, signed_y, delayed, output wire [3:0] part,
            output wire [1:0] dynamic_y, output wire [7:0] memory_y, output logic q);
            logic [7:0] mem[4]; wire [0:0] clock_bus; wire gated;
            assign clock_bus = clk; assign gated = clock_bus[0:0];
            always @(posedge gated) q <= a[0];
            assign good = a[7:0]; assign signed_y = s[7:0];
            assign part = a[3:0]; assign dynamic_y = a[idx+:2];
            assign memory_y = mem[idx][7:0]; assign #1 delayed = a[7:0];
            endmodule''')
        self.assertEqual(len(result['candidates']), 1)
        row = result['candidates'][0]
        self.assertEqual((row['before'], row['after']), ('a[7:0]', 'a'))
        self.assertGreater(result['rejected_sites'], 5)

    def test_all_elaborated_parameter_instances_must_be_safe(self):
        result = self.native('''module leaf #(parameter W=8)(input wire [W-1:0] x, output wire [7:0] y);
            assign y=x[7:0]; endmodule
            module top(input wire [15:0] a, output wire [7:0] y,z);
            leaf #(8) one(a[7:0],y); leaf #(16) two(a,z); endmodule''')
        self.assertEqual(result['candidates'], [])

    def test_macro_is_not_a_textual_rewrite_target(self):
        result = self.native('''`define FULL(a) a[7:0]
            module top(input wire[7:0] a, output wire[7:0] y);
            assign y = `FULL(a); endmodule''')
        self.assertEqual(result['candidates'], [])

    def test_rtl_ingest_preserves_actual_source_file(self):
        out = self.root / 'raw.json'
        with (self.root / 'frontend.log').open('w') as log:
            subprocess.run([str(BIN/'grhsim32_frontend'), str(out), 'rewrite_fixture',
                            str(FIXTURES/'rewrite_fixture.sv')], stdout=log, stderr=subprocess.STDOUT, check=True)
        data = json.loads(out.read_text())
        found = []
        def walk(x):
            if isinstance(x, dict):
                if 'file' in x and str(x['file']).endswith('rewrite_fixture.sv') and x.get('line',0)>0:
                    found.append(x)
                for value in x.values(): walk(value)
            elif isinstance(x, list):
                for value in x: walk(value)
        walk(data)
        self.assertTrue(found, 'RTL-to-GRH source provenance is missing')

    def test_hotspot_gate_and_two_100000_cycle_verilator_trajectories(self):
        source = FIXTURES / 'rewrite_fixture.sv'
        filelist = self.root / 'input.f'; filelist.write_text(str(source)+'\n')
        ast = self.root / 'fixture-ast.json'
        subprocess.run([str(BIN/'grhsim32_rtl_rewrite'), str(ast), 'rewrite_fixture', str(source)], check=True)
        row = json.loads(ast.read_text())['candidates'][0]
        span = source_span(row, FIXTURES)
        mapping = self.root / 'source_map.json'
        mapping.write_text(json.dumps(dict(source_files={span['file']:identity(source)})))
        report = self.root / 'report.json'
        report.write_text(json.dumps(dict(status='pass', source_associations=[])))
        args = SimpleNamespace(source_map=mapping, report=report, filelist=filelist, top='rewrite_fixture',
                               native_tool=BIN/'grhsim32_rtl_rewrite', read_args=None, output=self.root/'empty')
        propose(args)
        self.assertEqual(json.loads((args.output/'manifest.json').read_text())['status'], 'no-candidate')
        report.write_text(json.dumps(dict(status='pass', source_associations=[dict(**span, associated_batch_ns=100)])))
        args.output = self.root / 'candidate'; propose(args)
        candidate = json.loads((args.output/'manifest.json').read_text())
        self.assertIn('assign y = a;', Path(candidate['rewritten']['path']).read_text())
        stimuli = []
        for seed in (17, 29):
            rng = random.Random(seed); path = self.root / f'inputs-{seed}.jsonl'; stimuli.append(path)
            with path.open('w') as f:
                for cycle in range(100000):
                    f.write(json.dumps(dict(cycle=cycle, inputs=dict(a=rng.randrange(256),
                        reset=int(cycle<3 or rng.randrange(1000)==0))), separators=(',',':'))+'\n')
        command = [sys.executable, str(FIXTURES/'verilator_trace.py'), '--rtl', '{rtl}',
                   '--stimulus', '{stimulus}', '--trace', '{trace}']
        commands = self.root / 'commands.json'; commands.write_text(json.dumps(dict(baseline=command,candidate=command)))
        verification = self.root / 'verification'
        verify(SimpleNamespace(manifest=args.output/'manifest.json', commands=commands, stimulus=stimuli,
                               cycles=100000, timeout=300, output=verification))
        result = json.loads((verification/'verification.json').read_text())
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(sum(r.get('cycles',0) for r in result['records']), 200000)
        print('VERILATOR DIFFERENTIAL ARTIFACTS', verification)


if __name__ == '__main__':
    unittest.main()

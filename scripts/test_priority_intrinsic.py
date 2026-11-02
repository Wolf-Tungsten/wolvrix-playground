import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'build/grhsim32-tools/bin/grhsim32_frontend'
ARTIFACTS=ROOT/'wolvrix/build/artifacts/priority-intrinsic/frontend-tests'

class IntrinsicImportTests(unittest.TestCase):
    def convert(self,text,name):
        ARTIFACTS.mkdir(parents=True,exist_ok=True)
        path=ARTIFACTS/(name+'.sv');path.write_text(text)
        output=path.with_suffix('.json')
        result=subprocess.run([TOOL,output,'top',path],text=True,capture_output=True)
        path.with_suffix('.log').write_text(result.stdout+result.stderr)
        return result, json.loads(output.read_text()) if result.returncode==0 else None

    @staticmethod
    def source(name='wolvrix_ctz_v1_w7',arg='byte',out='int',body=None):
        call=name+'(x,y);'
        return (f'import "DPI-C" context function void {name}(input {arg} x, output {out} y);\n'
                f'module top(input {arg} x,input bit clock,input bit enable,output {out} y);\n'
                +(body or 'always_comb '+call)+'\nendmodule\n')

    def test_arbitrary_width_transport_and_pure_graph(self):
        for width,carrier in [(1,'bit'),(7,'byte'),(17,'int'),(64,'longint'),(65,'bit [64:0]'),(129,'bit [128:0]')]:
            with self.subTest(width=width):
                result,data=self.convert(self.source(name=f'wolvrix_ctz_v1_w{width}',arg=carrier),f'width{width}')
                self.assertEqual(result.returncode,0,result.stderr)
                ops=[op for g in data['graphs'] for op in g['ops']]
                self.assertEqual(sum(op['kind']=='kCountTrailingZeros' for op in ops),1)
                self.assertFalse(any(op['kind'] in ('kDpicCall','kDpicImport','kRegister','kLatch') for op in ops))
                self.assertTrue(next(op for op in ops if op['kind']=='kCountTrailingZeros').get('loc'))

    def test_contract_rejections(self):
        cases=dict(version=self.source(name='wolvrix_ctz_v2_w7'),
            zero=self.source(name='wolvrix_ctz_v1_w0'),
            width=self.source(arg='longint'),result=self.source(out='shortint'),
            fourstate=self.source(arg='logic [7:0]'),
            clock=self.source(body='always @(posedge clock) wolvrix_ctz_v1_w7(x,y);'),
            enable=self.source(body='always_comb if (enable) wolvrix_ctz_v1_w7(x,y);'),
            alias=self.source().replace('context function','context another_function = function'))
        for name,source in cases.items():
            with self.subTest(case=name):
                result,_=self.convert(source,'reject-'+name)
                self.assertNotEqual(result.returncode,0)

    def test_ordinary_clocked_dpi_is_preserved(self):
        result,data=self.convert(self.source(name='ordinary_function',body='always @(posedge clock) ordinary_function(x,y);'),'ordinary')
        self.assertEqual(result.returncode,0,result.stderr)
        kinds=[op['kind'] for g in data['graphs'] for op in g['ops']]
        self.assertIn('kDpicCall',kinds);self.assertNotIn('kCountTrailingZeros',kinds)

if __name__=='__main__':unittest.main()

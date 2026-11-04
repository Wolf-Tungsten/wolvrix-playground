import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'build/grhsim32-tools/bin/grhsim32_frontend'
ARTIFACTS=ROOT/'wolvrix/build/artifacts/decode-table-study/frontend-tests'


class DecodeTransportTests(unittest.TestCase):
    @staticmethod
    def source(payload='WDT1|P|5|9|2,7|0|1ff|3,1,1a0,1ff',dynamic=False,body=None):
        n=len(payload.encode());name=f'wolvrix_decode_table_v1_i5_o9_b{n}'
        value=f"{n*8}'h{payload.encode().hex()}" if not dynamic else 'table_input'
        call=f'{name}(x,{value},y);'
        return (f'import "DPI-C" context function void {name}(input byte x,input bit [{n*8-1}:0] payload,output shortint y);\n'
            f'module top(input byte x,input bit clock,enable,input bit [{n*8-1}:0] table_input,output shortint y);\n'
            +(body or 'always_comb CALL').replace('CALL',call)+'\nendmodule\n')

    def convert(self,text,name):
        ARTIFACTS.mkdir(parents=True,exist_ok=True);sv=ARTIFACTS/(name+'.sv');sv.write_text(text)
        result=subprocess.run([TOOL,sv.with_suffix('.json'),'top',sv],capture_output=True,text=True)
        sv.with_suffix('.log').write_text(result.stdout+result.stderr)
        return result,json.loads(sv.with_suffix('.json').read_text()) if not result.returncode else None

    def test_pure_single_dependency(self):
        result,data=self.convert(self.source(),'pure')
        self.assertEqual(result.returncode,0,result.stderr)
        ops=[o for g in data['graphs'] for o in g['ops']]
        op=next(o for o in ops if o['kind']=='kDecodeTable')
        self.assertEqual(len(op['in']),1);self.assertIn('decode.table',op['attrs'])
        self.assertFalse(any(o['kind'] in ['kDpicCall','kDpicImport'] for o in ops))
        self.assertTrue(op['loc'])

    def test_reject_invalid_contract(self):
        cases=dict(version=self.source().replace('table_v1','table_v2'),
            width=self.source().replace('input byte x','input longint x'),
            fourstate=self.source().replace('input byte x','input logic [7:0] x'),
            nonconstant=self.source(dynamic=True),
            clock=self.source(body='always @(posedge clock) CALL'),
            enable=self.source(body='always_comb if (enable) CALL'),
            alias=self.source().replace('context function','context other = function'),
            payload_width=self.source(payload='WDT1|P|5|8|8|0|ff|3,1,a0,ff'),
            field_width=self.source(payload='WDT1|P|5|9|7|0|1ff|3,1,a0,1ff'),
            unknown_mask=self.source(payload='WDT1|P|5|9|9|0|1ff|x,1,a0,1ff'),
            key_outside_mask=self.source(payload='WDT1|P|5|9|9|0|1ff|1,2,a0,1ff'),
            conflict=self.source(payload='WDT1|T|5|9|9|0|1ff|1,1,1,1;2,2,0,1'))
        for name,source in cases.items():
            with self.subTest(name=name):
                result,_=self.convert(source,name)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Invalid decode-table intrinsic',result.stdout+result.stderr)


if __name__=='__main__':unittest.main()

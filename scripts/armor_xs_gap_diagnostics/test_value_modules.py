"""Check FIRRTL instance traversal and aggregate signal ownership."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

import value_modules


class SignalOwnerTest(TestCase):
    def test_instance_and_aggregate_paths(self):
        with TemporaryDirectory() as folder:
            fir = Path(folder) / "SimTop.fir"
            fir.write_text(
                "  public module SimTop :\n"
                "    inst ftq of Ftq\n"
                "  module Ftq :\n"
                "    reg perfQueue : { cfiAttr : { branchType : UInt<2>}[32]}[64], clock\n"
                "    inst reader of Reader\n"
                "  module Reader :\n"
                "    output data : UInt<2>\n"
            )
            with patch.object(value_modules, "FIR", fir):
                tree = value_modules.fir_hierarchy()
        self.assertEqual(value_modules.signal_owner("ftq__DOT__reader__DOT__data", tree), "Reader")
        self.assertEqual(
            value_modules.signal_owner("ftq__DOT__perfQueue__DOT__cfiAttr__DOT__branchType$NEXT", tree), "Ftq"
        )
        self.assertIsNone(value_modules.signal_owner("ftq__DOT__unknown__DOT__field", tree))


if __name__ == "__main__":
    main()

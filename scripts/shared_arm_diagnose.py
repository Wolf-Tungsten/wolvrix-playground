#!/usr/bin/env python3
"""One serial post-measurement PMU sample per frozen shared-arm XS model."""
import argparse
from pathlib import Path
import xiangshan_cv32_ablation_measure as protocol
import xiangshan_cv32_ablation_pmu as pmu


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args(); out = args.source.resolve()
    protocol.VARIANTS = pmu.VARIANTS = ('full', 'candidate')
    protocol.ROUNDS = pmu.ROUNDS = 3
    pmu.diagnose(out, out / 'measurement', out / 'pmu')

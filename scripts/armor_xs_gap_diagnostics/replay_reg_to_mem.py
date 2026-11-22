"""Replay reg-to-mem on a pre-pass checkpoint and export original write-port identities."""
import argparse
from pathlib import Path

import wolvrix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-alternatives", type=int)
    args = parser.parse_args()
    with wolvrix.Session() as session:
        session.read_json_file(str(args.checkpoint), out_design="design.main")
        session.run_pass("reg-to-mem", design="design.main", ordered_writes=True,
                         decoded_write_storage=True, min_decoded_write_alternatives=args.min_alternatives,
                         group_report=str(args.report))


if __name__ == "__main__":
    main()

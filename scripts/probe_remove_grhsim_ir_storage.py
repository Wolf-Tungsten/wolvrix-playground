"""Isolate generated store construction from the model and its runtime."""

import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "ptmp/remove-grhsim-ir"
    if not args.output.resolve().is_relative_to(root):
        parser.error("output must be under ptmp/remove-grhsim-ir")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.synthetic:
        targets = []
        for count in (1000, 65534, 65535, 65536, 70000):
            for initialized in (False, True):
                name = f"fields-{count}-dmi-{int(initialized)}"
                text = "#include <cstdio>\n#include <memory>\n#include <string>\nstruct Store {\n"
                text += "".join(f"unsigned char v{i}" + ("{}" if initialized else "") + ";\n" for i in range(count))
                text += "std::string text{};\n};\nint main() { auto store=std::make_unique<Store>();\n"
                text += f'std::fprintf(stderr,"{name}: bytes=%zu string=%p\\n",sizeof(*store),(void*)store->text.data());\n'
                text += "if (!store->text.data()) return 1; store->text.clear(); }\n"
                (args.output / f"{name}.cpp").write_text(text)
                targets.append(name)
        make = ".PHONY: all " + " ".join(targets) + "\nall: " + " ".join(targets) + "\n"
        for name in targets:
            make += f"{name}:\n\t$(CXX) -std=c++20 -O$(OPT) {name}.cpp -o {name}\n\t./{name}\n"
        (args.output / "Makefile").write_text(make)
        return
    header = args.header.read_text()
    body = header.split("    struct nonSinkBoundaryStoreType {\n", 1)[1].split("    }", 1)[0]
    body = body.replace("nonSinkBoundaryStoreType()", "Store()")
    fields = re.findall(r"std::string (\w+)(?:\{\})?;", body)
    if not fields:
        parser.error("store has no strings")
    text = "#include <array>\n#include <cstdint>\n#include <cstdio>\n#include <memory>\n#include <string>\n"
    text += "struct Store {\n" + body + "};\n"
    text += "int main() { auto store=std::make_unique<Store>();\n"
    text += f'std::fprintf(stderr,"bytes=%zu string=%p\\n", sizeof(*store), (void*)store->{fields[0]}.data());\n'
    text += f"if (!store->{fields[0]}.data()) return 1;\n"
    text += "}\n"
    (args.output / "probe.cpp").write_text(text)
    print(f"fields={len(body.splitlines())} strings={len(fields)} first={fields[0]}", flush=True)


if __name__ == "__main__":
    main()

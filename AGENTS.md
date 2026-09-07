# Repository Guidelines

## Project Structure & Module Organization
- Core sources live in `wolvrix/lib/core/` with public headers in `wolvrix/include/`; the Python bindings live under `wolvrix/app/pybind` and package `wolvrix`.
- Wolvrix tests sit under `wolvrix/tests/{grh,ingest,transform,emit,store}` with module fixtures under `wolvrix/tests/<module>/data`; shared suites live in `testcase/{hdlbits,openc910,xiangshan,xs-bugcase}`. Test-only artifacts are written to `wolvrix/build/artifacts` (created by CMake).
- Source files:
  - `wolvrix/lib/core/grh.cpp` - GRH (Graph RTL Hierarchy) implementation
  - `wolvrix/lib/core/ingest.cpp` - Convert SystemVerilog AST to GRH
  - `wolvrix/lib/core/transform.cpp` - Transformation passes (constant folding, dead code elimination, etc.)
  - `wolvrix/lib/transform/*.cpp` - Built-in transform passes
  - `wolvrix/lib/core/emit.cpp` - Emit base implementation and shared emit infrastructure
  - `wolvrix/lib/emit/*.cpp` - Concrete emit implementations
  - `wolvrix/lib/core/store.cpp` - Store GRH as JSON
  - `wolvrix/lib/core/load.cpp` - Load GRH from JSON
- Documentation and design notes are in `wolvrix/docs/` (e.g., GRH spec, overview); keep feature-level docs there.
- External dependencies are vendored as git submodules under `wolvrix/external/` (notably `wolvrix/external/slang`); ensure `git submodule update --init --recursive` before building.
- Generated outputs land in `wolvrix/build/bin` (wolvrix binaries) and `build/hdlbits` (HDLBits sims); avoid committing these.

## Build, Test, and Development Commands
- **Build/test/install commands must always go through an existing project `Makefile` target. Do not manually compose or invoke `cmake`, `ctest`, `pip`, compiler, linker, or equivalent build commands. If a required workflow has no Makefile target, add the target to the Makefile first, then invoke that target.**
- Do not copy or manually assemble the underlying `cmake`, `ctest`, `pip`, compiler, or linker commands from the examples or build logs. Find and use the corresponding existing `Makefile` target; when none exists, add one before running the workflow.
- Keep command logs and temporary workflow artifacts under the repository's `ptmp/` directory; do not write task output to `/tmp` or other paths outside the project.
- HDLBits flow: `make run_hdlbits_test DUT=001` (or `make run_all_hdlbits_tests`) builds the parser, emits SV/JSON, and runs Verilator; needs Verilator in PATH.
- For Python package setup or script workflows, use the repository's `make py_install` and relevant Makefile target; direct `python3`/`pip` invocation is prohibited for build, test, or install work.

## Helper Implementation Performance
- Runtime helpers, especially generated C++ helpers for wide values, must follow the established legacy route as the performance reference.
- Prefer pointer-based, caller-provided output buffers (and local frame/boundary buffers where applicable). Avoid return-by-value `std::array` helpers and avoid creating large temporary wide-value copies in hot paths.
- Before adding a new helper or changing its ABI, inspect the corresponding legacy implementation and preserve its allocation, aliasing, and data-movement strategy unless a measured reason justifies a deviation.

## Coding Style & Naming Conventions
- C++20 code with 4-space indentation and braces on the same line as control statements; keep includes ordered and minimal.
- Use the `wolvrix` namespace with module-specific sub-namespaces; prefer explicit types unless `auto` improves readability.
- Keep public headers in `include/core/`, `include/emit/`, or `include/transform/`, aligned with implementations in `lib/core/`, `lib/emit/`, or `lib/transform/`; lean on `std::filesystem::path` for paths and STL containers for ownership.
- Mirror existing diagnostics/log patterns (e.g., `ConvertDiagnostics`, `PassDiagnostics`, `EmitDiagnostics`) and keep comments terse; avoid introducing non-ASCII identifiers.

## Testing Guidelines
- Tests are standalone executables registered via CTest; they fail by returning non-zero. Place new cases alongside their module (e.g., `tests/ingest/`).
- Name targets descriptively (`store-json`, `ingest-symbol-collector`, etc.) and wire fixture paths through `target_compile_definitions` in `CMakeLists.txt`.
- Store fixtures in `wolvrix/tests/<module>/data` (shared suites stay in `testcase/...`); write artifacts only under `wolvrix/build/artifacts` or `build/hdlbits` to keep the tree clean.
- For HDLBits-style checks, ensure both DUT (`testcase/hdlbits/dut/dut_*.v`) and TB (`testcase/hdlbits/tb/tb_*.cpp`) exist and match by ID.

## Documentation Lessons
- When describing IR or normalized forms (e.g., `kMemoryWritePort`), explicitly define each operand and show small input/output examples; do not assume the reader knows the intended normalization.

## Commit & Pull Request Guidelines
- Commits follow conventional prefixes (`feat`, `fix`, `test`, `docs`, `chore`, `bump`); keep scopes brief (e.g., `feat: optimize slice emit`).
- Keep changes atomic and include updated fixtures/docs when behavior shifts; run `ctest` and relevant `make run_hdlbits_test` targets before pushing.
- PRs should explain intent, list tests executed, and link related issues; include CLI output snippets or artifact notes when helpful for reviewers.

"""Count and specialize the scalar change sites declared by the GrhSIM emitter."""
import gzip
import hashlib
import json
import re
import struct
from pathlib import Path

MARKER = re.compile(rb"^#ifdef GRHSIM_(SPARSE|EAGER)_([0-9]+)$", re.MULTILINE)
ROW = struct.Struct("=QQ")
COUNTERS = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
namespace {
struct SiteCount {
    std::atomic<std::uint64_t> visits{}, changes{};
};
SiteCount site_counts[@SIZE@];
struct WriteSiteCounts {
    ~WriteSiteCounts() {
        auto *file = std::fopen(@PATH@, "wb");
        if (!file) std::abort();
        for (const auto &count : site_counts) {
            const std::uint64_t row[] = {count.visits.load(), count.changes.load()};
            if (std::fwrite(row, sizeof(row), 1, file) != 1) std::abort();
        }
        if (std::fclose(file) != 0) std::abort();
    }
} write_site_counts;
}
#define GRHSIM_COUNT_SITE(kind, id, changed) do { \
    auto &count = site_counts[GRHSIM_INDEX_##kind##id]; \
    count.visits.fetch_add(1, std::memory_order_relaxed); \
    if (changed) count.changes.fetch_add(1, std::memory_order_relaxed); \
} while (false)
"""


def fingerprinted_sources(model):
    for path in sorted(model.iterdir()):
        if path.suffix in (".cpp", ".h", ".hpp") or path.name == "Makefile":
            data = path.read_bytes()
            yield path, data, path.name.encode() + b"\0" + hashlib.sha256(data).digest()


def model_digest(model):
    digest = hashlib.sha256()
    for _, _, entry in fingerprinted_sources(model):
        digest.update(entry)
    return digest.hexdigest()


class ChangeSites:
    def __init__(self, model, work):
        self.work = work
        self.shards = {}
        digest = hashlib.sha256()
        for path, data, entry in fingerprinted_sources(model):
            digest.update(entry)
            if path.suffix != ".cpp":
                continue
            # The same graph value can occur in specialized copies of a batch.
            sites = sorted({(kind.decode(), int(number)) for kind, number in MARKER.findall(data)})
            if sites:
                self.shards[path] = sites
                # Always a private PGO build copy. The emitted model remains usable by itself.
                path.write_bytes(b'#include "' + self.header(path).name.encode() + b'"\n' + data)
        if not self.shards:
            raise ValueError("model has no change-site markers; emit with WOLVRIX_GRHSIM_CHANGE_SITE_PGO=1")
        self.digest = digest.hexdigest()

    @staticmethod
    def header(path):
        return path.with_suffix(".sites.h")

    def instrument(self):
        for path, sites in self.shards.items():
            raw = self.work / (path.stem + ".counts")
            with self.header(path).open("w") as out:
                out.write(COUNTERS.replace("@SIZE@", str(len(sites))).replace("@PATH@", json.dumps(str(raw))))
                for index, (kind, number) in enumerate(sites):
                    prefix = "V" if kind == "SPARSE" else "R"
                    out.write(f"#define GRHSIM_INDEX_{prefix}{number} {index}\n")

    def collect(self, destination, cycles):
        with gzip.open(destination, "wt") as out:
            print("grhsim-change-sites-v1", self.digest, cycles, file=out)
            for path, sites in self.shards.items():
                data = (self.work / (path.stem + ".counts")).read_bytes()
                if len(data) != len(sites) * ROW.size:
                    raise ValueError(f"incomplete site counts for {path.name}")
                print(path.name, len(sites), file=out)
                for (kind, number), (n, changed) in zip(sites, ROW.iter_unpack(data)):
                    print(kind, number, n, changed, file=out)

    def specialize(self, profile, policy, sparse_permille):
        selected = {"SPARSE": 0, "EAGER": 0}
        with gzip.open(profile, "rt") as src:
            version, digest, training_cycles = src.readline().split()
            cycles = int(training_cycles)
            if version != "grhsim-change-sites-v1" or digest != self.digest or cycles <= 0:
                raise ValueError("change-site profile does not match the emitted model")
            for path, sites in self.shards.items():
                if src.readline().split() != [path.name, str(len(sites))]:
                    raise ValueError(f"missing site inventory for {path.name}")
                with self.header(path).open("w") as out:
                    for kind, number in sites:
                        label, site, visits, changes = src.readline().split()
                        n, c = int(visits), int(changes)
                        if (label, int(site)) != (kind, number) or not 0 <= c <= n:
                            raise ValueError(f"invalid site count for {path.name} {kind} {number}")
                        if kind == "SPARSE":
                            use = policy in ("sparse", "both") and n >= max(1, cycles // 4) and 1000*c <= sparse_permille*n
                        else:
                            use = policy in ("commit", "both") and n >= max(1, cycles // 100) and 5*c >= n
                        if use:
                            print(f"#define GRHSIM_{kind}_{number} 1", file=out)
                            selected[kind] += 1
            if src.readline():
                raise ValueError("extra rows in change-site profile")
        return selected

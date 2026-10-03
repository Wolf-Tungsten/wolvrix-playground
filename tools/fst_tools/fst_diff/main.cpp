// fst_diff: inspect and compare FST waveforms (grhsim declared-symbols dumps
// vs Verilator reference traces).
//
// Subcommands:
//   signals <file.fst> [--filter sub]              list vars: handle width path
//   get <file.fst> <name> [--begin T] [--end T]
//       [--scale N/D] [--offset O]                 print "cycle value" changes
//   diff <a.fst> <b.fst> [options]                 first-divergence report over
//       [--strip-a P] [--strip-b P]                name-normalized shared vars
//       [--dotify-a C] [--dotify-b C]
//       [--scale-a N/D] [--scale-b N/D]
//       [--offset-a O] [--offset-b O]
//       [--begin T] [--end T] [--filter sub] [--max-report N]
//
// Name normalization for diff: path -> strip prefix -> replace dotify char
// with '.'. The grhsim dumps name vars "cpu$l_soc$core$..." (flat, one scope);
// Verilator traces nest scopes "TOP.SimTop.l_soc.core...". Typical usage:
//   diff wave.fst ref.fst --strip-a 'cpu$' --dotify-a '$' --strip-b 'TOP.SimTop.' \
//        --scale-b 1/2 --offset-b 0 --filter mainPipe
//
// Time model: change at raw time t lands in cycle floor((t+offset)*num/den);
// the last change within a cycle wins (the settled value). grhsim dumps one
// record per eval, so scale 1/1 offset 0 is exact there.
#include "fstapi.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace
{
    struct Options
    {
        std::string filter;
        std::string stripA, stripB;
        char dotifyA = '\0', dotifyB = '\0';
        int64_t offsetA = 0, offsetB = 0;
        uint64_t scaleNumA = 1, scaleDenA = 1, scaleNumB = 1, scaleDenB = 1;
        uint64_t begin = 0, end = std::numeric_limits<uint64_t>::max();
        uint32_t maxReport = 64;
    };

    [[noreturn]] void usage()
    {
        std::fprintf(stderr,
                     "usage:\n"
                     "  fst_diff signals <file.fst> [--filter sub]\n"
                     "  fst_diff get <file.fst> <name> [--scale N/D] [--offset O] [--begin T] [--end T]\n"
                     "  fst_diff diff <a.fst> <b.fst> [--strip-a P] [--strip-b P] [--dotify-a C] [--dotify-b C]\n"
                     "      [--scale-a N/D] [--scale-b N/D] [--offset-a O] [--offset-b O]\n"
                     "      [--begin T] [--end T] [--filter sub] [--max-report N]\n");
        std::exit(2);
    }

    uint64_t parseU64(const char *text)
    {
        char *end = nullptr;
        const auto value = std::strtoull(text, &end, 0);
        if (!end || *end) throw std::runtime_error(std::string("bad number: ") + text);
        return value;
    }

    int64_t parseI64(const char *text)
    {
        char *end = nullptr;
        const auto value = std::strtoll(text, &end, 0);
        if (!end || *end) throw std::runtime_error(std::string("bad number: ") + text);
        return value;
    }

    std::pair<uint64_t, uint64_t> parseScale(const char *text)
    {
        const std::string s(text);
        const auto slash = s.find('/');
        if (slash == std::string::npos) throw std::runtime_error("scale must be N/D: " + s);
        const auto num = parseU64(s.substr(0, slash).c_str());
        const auto den = parseU64(s.substr(slash + 1).c_str());
        if (!num || !den) throw std::runtime_error("scale must be non-zero: " + s);
        return {num, den};
    }

    struct ReaderGuard
    {
        fstReaderContext *ctx = nullptr;
        ~ReaderGuard()
        {
            if (ctx) fstReaderClose(ctx);
        }
    };

    struct VarInfo
    {
        std::string path; // scope.path.name, '.'-joined
        uint32_t width = 0;
        fstHandle handle = 0;
    };

    std::vector<VarInfo> readVars(fstReaderContext *ctx)
    {
        std::vector<VarInfo> vars;
        std::vector<std::string> scopes;
        while (fstHier *hier = fstReaderIterateHier(ctx))
        {
            if (hier->htyp == FST_HT_SCOPE)
            {
                scopes.emplace_back(hier->u.scope.name ? hier->u.scope.name : "");
                continue;
            }
            if (hier->htyp == FST_HT_UPSCOPE)
            {
                if (!scopes.empty()) scopes.pop_back();
                continue;
            }
            if (hier->htyp != FST_HT_VAR) continue;
            VarInfo var;
            for (std::size_t i = 0; i < scopes.size(); ++i)
            {
                if (i) var.path += '.';
                var.path += scopes[i];
            }
            if (!var.path.empty()) var.path += '.';
            var.path += hier->u.var.name ? hier->u.var.name : "";
            var.width = hier->u.var.length;
            var.handle = hier->u.var.handle;
            vars.push_back(std::move(var));
        }
        return vars;
    }

    std::string normalizeName(std::string path, const std::string &strip, char dotify)
    {
        if (!strip.empty() && path.compare(0, strip.size(), strip) == 0) path.erase(0, strip.size());
        if (dotify != '\0') std::replace(path.begin(), path.end(), dotify, '.');
        // Verilator FST vector names carry a packed-dimension suffix
        // ("sig [1:0]", unpacked elements "sig [3]"); drop it for matching.
        for (;;)
        {
            const auto close = path.find_last_of(']');
            if (close == std::string::npos || close + 1 != path.size()) break;
            const auto open = path.find_last_of('[', close);
            if (open == std::string::npos) break;
            const std::string_view inner(path.data() + open + 1, close - open - 1);
            const auto dimLike = [](std::string_view s) {
                if (s.empty()) return false;
                return std::all_of(s.begin(), s.end(), [](char c) {
                    return (c >= '0' && c <= '9') || c == ':' || c == ' ';
                });
            };
            if (!dimLike(inner)) break;
            std::size_t stem = open;
            while (stem > 0 && path[stem - 1] == ' ') --stem;
            path.erase(stem);
        }
        return path;
    }

    // Sparse per-var change list: sorted cycles, values interned in a pool.
    struct ChangeStream
    {
        std::vector<uint64_t> cycles;
        std::vector<uint32_t> valueIds;
    };

    struct Trace
    {
        std::vector<VarInfo> vars; // index == var slot
        std::unordered_map<std::string, uint32_t> varByName;
        std::deque<std::string> valuePool;
        std::unordered_map<std::string, uint32_t> valueIdByText;
        std::vector<ChangeStream> changes; // per wanted var slot

        uint32_t internValue(const unsigned char *text)
        {
            const std::string_view view(reinterpret_cast<const char *>(text));
            if (const auto it = valueIdByText.find(std::string(view)); it != valueIdByText.end()) return it->second;
            const auto id = static_cast<uint32_t>(valuePool.size());
            valuePool.emplace_back(view);
            valueIdByText.emplace(valuePool.back(), id);
            return id;
        }
    };

    struct CollectCtx
    {
        Trace *trace = nullptr;
        std::vector<int32_t> slotByHandle; // handle -> var slot, -1 when unwanted
        uint64_t scaleNum = 1, scaleDen = 1;
        int64_t offset = 0;
        uint64_t begin = 0, end = std::numeric_limits<uint64_t>::max();
        uint64_t droppedLate = 0;

        uint64_t cycleOf(uint64_t time) const
        {
            const int64_t shifted = static_cast<int64_t>(time) + offset;
            const auto adjusted = shifted < 0 ? int64_t(0) : shifted;
            return (static_cast<uint64_t>(adjusted) * scaleNum) / scaleDen;
        }
    };

    void changeCallback(void *user, uint64_t time, fstHandle handle, const unsigned char *value)
    {
        auto &ctx = *static_cast<CollectCtx *>(user);
        if (handle >= ctx.slotByHandle.size()) return;
        const int32_t slot = ctx.slotByHandle[handle];
        if (slot < 0) return;
        const uint64_t cycle = ctx.cycleOf(time);
        if (cycle < ctx.begin || cycle > ctx.end) return;
        auto &stream = ctx.trace->changes[slot];
        const uint32_t valueId = ctx.trace->internValue(value);
        // Last change within a cycle wins; same-value repeats collapse.
        if (!stream.cycles.empty() && stream.cycles.back() == cycle)
        {
            stream.valueIds.back() = valueId;
            ++ctx.droppedLate;
            return;
        }
        if (!stream.valueIds.empty() && stream.valueIds.back() == valueId) return;
        stream.cycles.push_back(cycle);
        stream.valueIds.push_back(valueId);
    }

    // Loads change streams for the wanted vars (name filter already applied to
    // wanted slots). Streams come out sorted by cycle (FST time is monotone).
    void collectChanges(const char *path, Trace &trace, CollectCtx &ctx)
    {
        fstReaderContext *raw = fstReaderOpen(path);
        if (!raw) throw std::runtime_error(std::string("failed to open fst: ") + path);
        ReaderGuard guard{raw};
        ctx.trace = &trace;
        fstHandle maxHandle = 0;
        for (const auto &var : trace.vars) maxHandle = std::max(maxHandle, var.handle);
        ctx.slotByHandle.assign(maxHandle + 1, -1);
        fstReaderClrFacProcessMaskAll(raw);
        bool any = false;
        for (std::size_t slot = 0; slot < trace.vars.size(); ++slot)
        {
            ctx.slotByHandle[trace.vars[slot].handle] = static_cast<int32_t>(slot);
            fstReaderSetFacProcessMask(raw, trace.vars[slot].handle);
            any = true;
        }
        if (any) fstReaderIterBlocks2(raw, changeCallback, nullptr, &ctx, nullptr);
    }

    Trace openTrace(const char *path, const std::string &strip, char dotify, const std::string &filter,
                    bool requireFilter)
    {
        fstReaderContext *raw = fstReaderOpen(path);
        if (!raw) throw std::runtime_error(std::string("failed to open fst: ") + path);
        ReaderGuard guard{raw};
        Trace trace;
        for (auto &var : readVars(raw))
        {
            std::string name = normalizeName(var.path, strip, dotify);
            if (!filter.empty() && name.find(filter) == std::string::npos) continue;
            var.path = std::move(name);
            const auto slot = static_cast<uint32_t>(trace.vars.size());
            trace.varByName.emplace(var.path, slot);
            trace.vars.push_back(std::move(var));
        }
        trace.changes.resize(trace.vars.size());
        if (requireFilter && trace.vars.empty())
            throw std::runtime_error(std::string("no vars match filter '") + filter + "' in " + path);
        return trace;
    }

    bool valuesEqual(const std::string &a, const std::string &b)
    {
        // Right-aligned compare, shorter side zero-extended (both traces are
        // two-state; x/z chars compare literally).
        const auto width = std::max(a.size(), b.size());
        const auto padA = width - a.size(), padB = width - b.size();
        for (std::size_t i = 0; i < width; ++i)
        {
            const char ca = i < padA ? '0' : a[i - padA];
            const char cb = i < padB ? '0' : b[i - padB];
            if (ca != cb) return false;
        }
        return true;
    }

    int cmdSignals(int argc, char **argv)
    {
        if (argc < 3) usage();
        Options opt;
        for (int i = 3; i < argc; i += 2)
        {
            if (std::strcmp(argv[i], "--filter") == 0 && i + 1 < argc) opt.filter = argv[i + 1];
            else usage();
        }
        auto trace = openTrace(argv[2], "", '\0', opt.filter, false);
        for (std::size_t slot = 0; slot < trace.vars.size(); ++slot)
        {
            const auto &var = trace.vars[slot];
            std::printf("%5u %4u %s\n", static_cast<unsigned>(var.handle), var.width, var.path.c_str());
        }
        std::fprintf(stderr, "[fst_diff] %zu vars\n", trace.vars.size());
        return 0;
    }

    int cmdGet(int argc, char **argv)
    {
        if (argc < 4) usage();
        const std::string target = argv[3];
        Options opt;
        for (int i = 4; i < argc; i += 2)
        {
            if (i + 1 >= argc) usage();
            if (std::strcmp(argv[i], "--scale") == 0) std::tie(opt.scaleNumA, opt.scaleDenA) = parseScale(argv[i + 1]);
            else if (std::strcmp(argv[i], "--offset") == 0) opt.offsetA = parseI64(argv[i + 1]);
            else if (std::strcmp(argv[i], "--begin") == 0) opt.begin = parseU64(argv[i + 1]);
            else if (std::strcmp(argv[i], "--end") == 0) opt.end = parseU64(argv[i + 1]);
            else usage();
        }
        auto trace = openTrace(argv[2], "", '\0', target, false);
        if (trace.vars.empty()) throw std::runtime_error("no var named like: " + target);
        CollectCtx ctx;
        ctx.scaleNum = opt.scaleNumA;
        ctx.scaleDen = opt.scaleDenA;
        ctx.offset = opt.offsetA;
        ctx.begin = opt.begin;
        ctx.end = opt.end;
        collectChanges(argv[2], trace, ctx);
        for (std::size_t slot = 0; slot < trace.vars.size(); ++slot)
        {
            std::printf("# %s (width %u)\n", trace.vars[slot].path.c_str(), trace.vars[slot].width);
            const auto &stream = trace.changes[slot];
            for (std::size_t i = 0; i < stream.cycles.size(); ++i)
                std::printf("%llu %s\n", static_cast<unsigned long long>(stream.cycles[i]),
                            trace.valuePool[stream.valueIds[i]].c_str());
        }
        return 0;
    }

    int cmdDiff(int argc, char **argv)
    {
        if (argc < 4) usage();
        Options opt;
        for (int i = 4; i < argc; i += 2)
        {
            if (i + 1 >= argc) usage();
            const std::string_view key = argv[i];
            if (key == "--strip-a") opt.stripA = argv[i + 1];
            else if (key == "--strip-b") opt.stripB = argv[i + 1];
            else if (key == "--dotify-a") opt.dotifyA = argv[i + 1][0];
            else if (key == "--dotify-b") opt.dotifyB = argv[i + 1][0];
            else if (key == "--scale-a") std::tie(opt.scaleNumA, opt.scaleDenA) = parseScale(argv[i + 1]);
            else if (key == "--scale-b") std::tie(opt.scaleNumB, opt.scaleDenB) = parseScale(argv[i + 1]);
            else if (key == "--offset-a") opt.offsetA = parseI64(argv[i + 1]);
            else if (key == "--offset-b") opt.offsetB = parseI64(argv[i + 1]);
            else if (key == "--begin") opt.begin = parseU64(argv[i + 1]);
            else if (key == "--end") opt.end = parseU64(argv[i + 1]);
            else if (key == "--filter") opt.filter = argv[i + 1];
            else if (key == "--max-report") opt.maxReport = static_cast<uint32_t>(parseU64(argv[i + 1]));
            else usage();
        }
        auto traceA = openTrace(argv[2], opt.stripA, opt.dotifyA, opt.filter, false);
        auto traceB = openTrace(argv[3], opt.stripB, opt.dotifyB, opt.filter, false);
        std::fprintf(stderr, "[fst_diff] vars: A=%zu B=%zu\n", traceA.vars.size(), traceB.vars.size());
        // Keep only shared names.
        std::vector<uint32_t> sharedA, sharedB;
        for (std::size_t slot = 0; slot < traceA.vars.size(); ++slot)
            if (const auto it = traceB.varByName.find(traceA.vars[slot].path); it != traceB.varByName.end())
            {
                sharedA.push_back(static_cast<uint32_t>(slot));
                sharedB.push_back(it->second);
            }
        std::fprintf(stderr, "[fst_diff] shared vars: %zu\n", sharedA.size());
        if (sharedA.empty())
        {
            std::printf("no shared vars\n");
            return 1;
        }
        std::unordered_map<uint32_t, uint32_t> keepA, keepB;
        for (std::size_t i = 0; i < sharedA.size(); ++i)
        {
            keepA.emplace(sharedA[i], static_cast<uint32_t>(i));
            keepB.emplace(sharedB[i], static_cast<uint32_t>(i));
        }
        const auto prune = [](Trace &trace, const std::unordered_map<uint32_t, uint32_t> &keep) {
            std::vector<VarInfo> vars(keep.size());
            for (const auto &[oldSlot, newSlot] : keep) vars[newSlot] = std::move(trace.vars[oldSlot]);
            trace.vars = std::move(vars);
            trace.changes.assign(trace.vars.size(), {});
        };
        prune(traceA, keepA);
        prune(traceB, keepB);
        CollectCtx ctxA, ctxB;
        ctxA.scaleNum = opt.scaleNumA;
        ctxA.scaleDen = opt.scaleDenA;
        ctxA.offset = opt.offsetA;
        ctxA.begin = opt.begin;
        ctxA.end = opt.end;
        ctxB.scaleNum = opt.scaleNumB;
        ctxB.scaleDen = opt.scaleDenB;
        ctxB.offset = opt.offsetB;
        ctxB.begin = opt.begin;
        ctxB.end = opt.end;
        collectChanges(argv[2], traceA, ctxA);
        collectChanges(argv[3], traceB, ctxB);
        std::size_t divergent = 0, silent = 0, reported = 0;
        for (std::size_t i = 0; i < traceA.vars.size(); ++i)
        {
            const auto &sa = traceA.changes[i];
            const auto &sb = traceB.changes[i];
            if (sa.cycles.empty() && sb.cycles.empty())
            {
                ++silent;
                continue;
            }
            // Merge-walk the two change lists over the union of cycles.
            std::size_t ia = 0, ib = 0;
            uint32_t curA = std::numeric_limits<uint32_t>::max(), curB = curA;
            uint64_t firstDiff = std::numeric_limits<uint64_t>::max();
            std::string firstA, firstB;
            while (ia < sa.cycles.size() || ib < sb.cycles.size())
            {
                const uint64_t nextA = ia < sa.cycles.size() ? sa.cycles[ia] : std::numeric_limits<uint64_t>::max();
                const uint64_t nextB = ib < sb.cycles.size() ? sb.cycles[ib] : std::numeric_limits<uint64_t>::max();
                const uint64_t cycle = std::min(nextA, nextB);
                if (nextA == cycle) curA = sa.valueIds[ia++];
                if (nextB == cycle) curB = sb.valueIds[ib++];
                if (curA == std::numeric_limits<uint32_t>::max() || curB == std::numeric_limits<uint32_t>::max())
                    continue; // one side has no value yet
                const auto &textA = traceA.valuePool[curA];
                const auto &textB = traceB.valuePool[curB];
                if (!valuesEqual(textA, textB))
                {
                    firstDiff = cycle;
                    firstA = textA;
                    firstB = textB;
                    break;
                }
            }
            if (firstDiff == std::numeric_limits<uint64_t>::max()) continue;
            ++divergent;
            if (reported < opt.maxReport)
            {
                ++reported;
                std::printf("%s width(A=%u,B=%u) first-diverge cycle=%llu A=%s B=%s\n", traceA.vars[i].path.c_str(),
                            traceA.vars[i].width, traceB.vars[i].width,
                            static_cast<unsigned long long>(firstDiff), firstA.c_str(), firstB.c_str());
            }
        }
        std::printf("[fst_diff] compared=%zu divergent=%zu silent=%zu\n", traceA.vars.size() - silent, divergent,
                    silent);
        return divergent ? 1 : 0;
    }
} // namespace

int main(int argc, char **argv)
{
    try
    {
        if (argc < 2) usage();
        const std::string_view cmd = argv[1];
        if (cmd == "signals") return cmdSignals(argc, argv);
        if (cmd == "get") return cmdGet(argc, argv);
        if (cmd == "diff") return cmdDiff(argc, argv);
        usage();
    }
    catch (const std::exception &error)
    {
        std::fprintf(stderr, "fst_diff: %s\n", error.what());
        return 2;
    }
}

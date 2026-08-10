// Standalone partition lab: faithful offline replica of
// wolvrix/lib/grhsim/am/grhsim_am_compute_graph_partition.cpp with knobs for
// the initial topological order, coarsening budget, DP capacity and segment
// penalty. Used to localize the supernode-align structural gap (NO0014).
//
// Input: raw .npy dumps produced by partition_lab_dump.py.
//
//   partition_lab --dir DUMP [--order mininstr|lifo] [--cap N]
//                 [--coarsen-budget N] [--no-coarsen] [--sibling-cap N]
//                 [--penalty D]

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <queue>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace {

uint32_t loadNpyHeader(std::ifstream &in, std::string &descr) {
    char magic[6];
    in.read(magic, 6);
    if (std::memcmp(magic, "\x93NUMPY", 6) != 0) {
        std::cerr << "bad npy magic\n";
        std::exit(1);
    }
    uint8_t major = 0, minor = 0;
    in.read(reinterpret_cast<char *>(&major), 1);
    in.read(reinterpret_cast<char *>(&minor), 1);
    uint32_t headerLen = 0;
    if (major == 1) {
        uint16_t len = 0;
        in.read(reinterpret_cast<char *>(&len), 2);
        headerLen = len;
    } else {
        in.read(reinterpret_cast<char *>(&headerLen), 4);
    }
    std::string header(headerLen, ' ');
    in.read(header.data(), headerLen);
    // parse shape "(N,)" and descr
    const auto dpos = header.find("'descr'");
    const auto colon = header.find(':', dpos);
    const auto q1 = header.find('\'', colon);
    const auto q2 = header.find('\'', q1 + 1);
    descr = header.substr(q1 + 1, q2 - q1 - 1);
    const auto spos = header.find("'shape'");
    const auto scolon = header.find(':', spos);
    const auto p1 = header.find('(', scolon);
    const auto p2 = header.find(')', p1);
    const std::string shape = header.substr(p1 + 1, p2 - p1 - 1);
    uint64_t n = 0;
    for (const char ch : shape) {
        if (isdigit(ch)) n = n * 10 + static_cast<uint64_t>(ch - '0');
    }
    return static_cast<uint32_t>(n);
}

template <typename T> std::vector<T> loadNpy(const std::string &path) {
    std::ifstream in(path, std::ios::binary);
    std::string descr;
    const uint32_t n = loadNpyHeader(in, descr);
    std::vector<T> data(n);
    in.read(reinterpret_cast<char *>(data.data()), static_cast<std::streamsize>(n * sizeof(T)));
    return data;
}

void sortedInsert(std::vector<uint32_t> &values, uint32_t value) {
    const auto it = std::lower_bound(values.begin(), values.end(), value);
    if (it == values.end() || *it != value) values.insert(it, value);
}
void sortedErase(std::vector<uint32_t> &values, uint32_t value) {
    const auto it = std::lower_bound(values.begin(), values.end(), value);
    if (it != values.end() && *it == value) values.erase(it);
}
void sortedUnionInto(std::vector<uint32_t> &host, const std::vector<uint32_t> &extra) {
    if (extra.empty()) return;
    std::vector<uint32_t> merged;
    merged.reserve(host.size() + extra.size());
    std::set_union(host.begin(), host.end(), extra.begin(), extra.end(), std::back_inserter(merged));
    host.swap(merged);
}

} // namespace

int main(int argc, char **argv) {
    std::string dir;
    std::string order = "mininstr";
    std::size_t cap = 128;
    std::size_t coarsenBudget = 256;
    std::size_t siblingCap = 30;
    double penalty = 1.0;
    bool coarsen = true;
    std::size_t repCap = 0;          // NO0015: cone-size cap for replication (0=off)
    double repBudgetMult = 1.0;      // max new atoms as a fraction of n
    std::size_t repMaxCopies = 256;  // per-atom fanout split limit
    std::string repMode = "absorb";  // absorb (fatten consumers) | copy (standalone atoms)
    bool repFreeze = false;          // gate fanout by the ORIGINAL graph (no cascade)
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        const auto next = [&]() { return std::string(argv[++i]); };
        if (arg == "--dir") dir = next();
        else if (arg == "--order") order = next();
        else if (arg == "--cap") cap = std::stoull(next());
        else if (arg == "--coarsen-budget") coarsenBudget = std::stoull(next());
        else if (arg == "--sibling-cap") siblingCap = std::stoull(next());
        else if (arg == "--penalty") penalty = std::stod(next());
        else if (arg == "--rep-cap") repCap = std::stoull(next());
        else if (arg == "--rep-budget-mult") repBudgetMult = std::stod(next());
        else if (arg == "--rep-max-copies") repMaxCopies = std::stoull(next());
        else if (arg == "--rep-mode") repMode = next();
        else if (arg == "--rep-freeze") repFreeze = true;
        else if (arg == "--no-coarsen") coarsen = false;
        else { std::cerr << "unknown arg " << arg << "\n"; return 1; }
    }

    const auto t0 = std::chrono::steady_clock::now();
    auto offsets = loadNpy<uint32_t>(dir + "/atom_offsets.npy");
    auto targets = loadNpy<uint32_t>(dir + "/atom_targets.npy");
    auto minInstr = loadNpy<uint32_t>(dir + "/atom_min_instr.npy");
    uint32_t n = static_cast<uint32_t>(offsets.size()) - 1;
    std::cerr << "atoms=" << n << " edges=" << targets.size() << "\n";

    // ---- NO0015 fanout absorption (pre-atom replication model) ----------
    // Models instruction-level replication before atom construction: atom A
    // (fanout K, small instruction cost) is absorbed into ALL its consumer
    // atoms -- equivalent to replicating A's cone per consumer and letting
    // the tree-atom fold absorb each copy. A's inputs then face K consumers
    // (fanout multiplied); the reverse-topo sweep cascades the absorption
    // upstream until it stops at hard leaves (mem.read/changed/host read
    // ports, never duplicated) or exceeds the instruction budget.
    std::size_t repCopies = 0;
    std::size_t repDupInstr = 0;
    if (repCap > 0) {
        const auto atomHard0 = loadNpy<uint8_t>(dir + "/atom_hard.npy");
        const auto atomICount0 = loadNpy<uint32_t>(dir + "/atom_icount.npy");
        std::vector<std::vector<uint32_t>> rNexts(n), rPrevs(n);
        for (uint32_t s = 0; s < n; ++s)
            for (uint32_t o = offsets[s]; o < offsets[s + 1]; ++o) {
                rNexts[s].push_back(targets[o]);
                rPrevs[targets[o]].push_back(s);
            }
        std::vector<uint32_t> topo;
        topo.reserve(n);
        {
            std::vector<uint32_t> stack;
            for (uint32_t s = 0; s < n; ++s)
                if (rPrevs[s].empty()) stack.push_back(s);
            std::vector<uint32_t> arrived(n, 0);
            while (!stack.empty()) {
                const uint32_t top = stack.back();
                stack.pop_back();
                topo.push_back(top);
                for (const uint32_t t : rNexts[top])
                    if (++arrived[t] == rPrevs[t].size()) stack.push_back(t);
            }
            if (topo.size() != n) { std::cerr << "cyclic graph in replication\n"; return 1; }
        }
        uint64_t totalInstr = 0;
        for (uint32_t s = 0; s < n; ++s) totalInstr += atomICount0[s];
        const uint64_t instrBudget =
            static_cast<uint64_t>(repBudgetMult * static_cast<double>(totalInstr));
        // freeze: gate fanout by the ORIGINAL outdegree (no cascade).
        std::vector<uint32_t> origOutdeg(n, 0);
        if (repFreeze)
            for (uint32_t s = 0; s < n; ++s)
                origOutdeg[s] = static_cast<uint32_t>(rNexts[s].size());
        std::vector<uint8_t> alive(n, 1);
        std::size_t absorbed = 0;
        if (repMode == "copy") {
            // Copy mode (user direction): duplicate the fanout atom itself as
            // standalone single-consumer atoms; chain merging (out1) then
            // glues each copy to its consumer's cluster. Inputs stay shared.
            std::vector<uint32_t> minInstrExt(minInstr.begin(), minInstr.end());
            uint32_t nTotal = n;
            for (auto it = topo.rbegin(); it != topo.rend(); ++it) {
                const uint32_t a = *it;
                if (alive[a] == 0 || atomHard0[a] != 0) continue;
                const std::vector<uint32_t> consumers = rNexts[a];
                const std::size_t fanoutNow = consumers.size();
                const std::size_t gate = repFreeze ? origOutdeg[a] : fanoutNow;
                if (gate < 2 || fanoutNow > repMaxCopies) continue;
                const uint64_t cost = atomICount0[a];
                if (cost == 0 || cost > repCap) continue;
                const uint64_t dup = static_cast<uint64_t>(fanoutNow - 1) * cost;
                if (repDupInstr + dup > instrBudget) break;
                for (std::size_t k = 1; k < fanoutNow; ++k) {
                    const uint32_t consumer = consumers[k];
                    const uint32_t copy = nTotal++;
                    rNexts.push_back(std::vector<uint32_t>{consumer});
                    rPrevs.push_back(rPrevs[a]);
                    minInstrExt.push_back(minInstrExt[a]);
                    for (const uint32_t p : rPrevs[copy]) rNexts[p].push_back(copy);
                    sortedErase(rPrevs[consumer], a);
                    sortedInsert(rPrevs[consumer], copy);
                    ++absorbed;
                }
                rNexts[a] = {consumers.front()};
                repDupInstr += dup;
            }
            // rebuild CSR (all original atoms survive; copies appended)
            std::vector<uint64_t> all;
            all.reserve(targets.size() + absorbed * 2);
            for (uint32_t s = 0; s < nTotal; ++s)
                for (const uint32_t t : rNexts[s])
                    all.push_back((static_cast<uint64_t>(s) << 32) | t);
            std::sort(all.begin(), all.end());
            all.erase(std::unique(all.begin(), all.end()), all.end());
            offsets.assign(nTotal + 1, 0);
            for (const uint64_t e : all) ++offsets[static_cast<uint32_t>(e >> 32) + 1];
            std::partial_sum(offsets.begin(), offsets.end(), offsets.begin());
            targets.resize(all.size());
            {
                std::vector<uint32_t> cursor(offsets.begin(), offsets.end() - 1);
                for (const uint64_t e : all)
                    targets[cursor[static_cast<uint32_t>(e >> 32)]++] = static_cast<uint32_t>(e);
            }
            minInstr = std::move(minInstrExt);
            n = nTotal;
            repCopies = absorbed;
            std::cerr << "  [lab] copy-rep copies=" << absorbed
                      << " dupInstr=" << repDupInstr << " atoms=" << n
                      << " edges=" << targets.size() << "\n";
        } else {
        for (auto it = topo.rbegin(); it != topo.rend(); ++it) {
            const uint32_t a = *it;
            if (alive[a] == 0 || atomHard0[a] != 0) continue;
            std::vector<uint32_t> &ns = rNexts[a];
            const std::size_t fanout = ns.size();
            if (repFreeze && origOutdeg[a] < 2) continue;
            if (fanout < 2 || fanout > repMaxCopies) continue;
            const uint64_t cost = atomICount0[a];
            if (cost == 0 || cost > repCap) continue;
            const uint64_t dup = static_cast<uint64_t>(fanout - 1) * cost;
            if (repDupInstr + dup > instrBudget) break;
            // absorb a into every consumer: a's inputs re-point to each
            // consumer; a dies (no orphan needed: the lab does not model
            // observability pins).
            for (const uint32_t c : ns) {
                sortedErase(rPrevs[c], a);
                for (const uint32_t p : rPrevs[a]) {
                    if (p == c) continue;
                    sortedInsert(rPrevs[c], p);
                    sortedInsert(rNexts[p], c);
                }
            }
            for (const uint32_t p : rPrevs[a]) sortedErase(rNexts[p], a);
            ns.clear();
            rPrevs[a].clear();
            alive[a] = 0;
            repDupInstr += dup;
            ++absorbed;
        }
        // rebuild CSR over alive atoms (dense remap)
        std::vector<uint32_t> remap(n, std::numeric_limits<uint32_t>::max());
        uint32_t nTotal = 0;
        for (uint32_t s = 0; s < n; ++s)
            if (alive[s] != 0) remap[s] = nTotal++;
        std::vector<uint64_t> all;
        all.reserve(targets.size());
        for (uint32_t s = 0; s < n; ++s) {
            if (alive[s] == 0) continue;
            for (const uint32_t t : rNexts[s])
                all.push_back((static_cast<uint64_t>(remap[s]) << 32) | remap[t]);
        }
        std::sort(all.begin(), all.end());
        all.erase(std::unique(all.begin(), all.end()), all.end());
        offsets.assign(nTotal + 1, 0);
        for (const uint64_t e : all) ++offsets[static_cast<uint32_t>(e >> 32) + 1];
        std::partial_sum(offsets.begin(), offsets.end(), offsets.begin());
        targets.resize(all.size());
        {
            std::vector<uint32_t> cursor(offsets.begin(), offsets.end() - 1);
            for (const uint64_t e : all)
                targets[cursor[static_cast<uint32_t>(e >> 32)]++] = static_cast<uint32_t>(e);
        }
        std::vector<uint32_t> newMin(nTotal, 0);
        for (uint32_t s = 0; s < n; ++s)
            if (alive[s] != 0) newMin[remap[s]] = minInstr[s];
        minInstr = std::move(newMin);
        n = nTotal;
        repCopies = absorbed;
        std::cerr << "  [lab] absorption absorbed=" << absorbed
                  << " dupInstr=" << repDupInstr << " atoms=" << n
                  << " edges=" << targets.size() << "\n";
        }
    }

    // ---- initial topological order (rid space) -------------------------
    std::vector<uint32_t> atomOfRid;
    atomOfRid.reserve(n);
    {
        std::vector<uint32_t> indegree(n, 0);
        for (uint32_t atom = 0; atom < n; ++atom)
            for (uint32_t off = offsets[atom]; off < offsets[atom + 1]; ++off) ++indegree[targets[off]];
        if (order == "mininstr") {
            // production: Kahn with min-heap on (atomMinInstruction, atom)
            using Cand = std::tuple<uint32_t, uint32_t>;
            std::priority_queue<Cand, std::vector<Cand>, std::greater<>> ready;
            for (uint32_t atom = 0; atom < n; ++atom)
                if (indegree[atom] == 0) ready.emplace(minInstr[atom], atom);
            while (!ready.empty()) {
                const uint32_t atom = std::get<1>(ready.top());
                ready.pop();
                atomOfRid.push_back(atom);
                for (uint32_t off = offsets[atom]; off < offsets[atom + 1]; ++off) {
                    const uint32_t t = targets[off];
                    if (--indegree[t] == 0) ready.emplace(minInstr[t], t);
                }
            }
        } else if (order == "dfs") {
            // reverse post-order of an iterative DFS from sources (ascending
            // atom id); valid topological order with cone locality.
            std::vector<uint32_t> post;
            post.reserve(n);
            std::vector<uint8_t> state(n, 0); // 0=unseen 1=on-stack 2=done
            std::vector<uint32_t> stack;
            for (uint32_t seed = 0; seed < n; ++seed) {
                if (indegree[seed] != 0 || state[seed] != 0) continue;
                stack.push_back(seed);
                state[seed] = 1;
                while (!stack.empty()) {
                    const uint32_t top = stack.back();
                    bool pushed = false;
                    for (uint32_t off = offsets[top]; off < offsets[top + 1]; ++off) {
                        const uint32_t t = targets[off];
                        if (state[t] == 0) {
                            stack.push_back(t);
                            state[t] = 1;
                            pushed = true;
                            break;
                        }
                    }
                    if (!pushed) {
                        stack.pop_back();
                        state[top] = 2;
                        post.push_back(top);
                    }
                }
            }
            // nodes unreachable from sources (none in a DAG with sources)
            for (uint32_t atom = 0; atom < n; ++atom)
                if (state[atom] == 0) post.push_back(atom);
            // reverse post-order, but must be topological: edges forward.
            std::vector<uint32_t> rpo(post.rbegin(), post.rend());
            // rpo is topological only if every edge goes forward in rpo;
            // verify cheaply and fall back to Kahn if violated.
            std::vector<uint32_t> pos(n, 0);
            for (uint32_t i = 0; i < n; ++i) pos[rpo[i]] = i;
            bool ok = true;
            for (uint32_t atom = 0; atom < n && ok; ++atom)
                for (uint32_t off = offsets[atom]; off < offsets[atom + 1]; ++off)
                    if (pos[targets[off]] <= pos[atom]) { ok = false; break; }
            if (ok) {
                atomOfRid = std::move(rpo);
            } else {
                std::cerr << "dfs rpo not topological, falling back to lifo\n";
                std::vector<uint32_t> stk;
                for (uint32_t atom = 0; atom < n; ++atom)
                    if (indegree[atom] == 0) stk.push_back(atom);
                std::vector<uint32_t> arrived(n, 0);
                while (!stk.empty()) {
                    const uint32_t top = stk.back();
                    stk.pop_back();
                    atomOfRid.push_back(top);
                    for (uint32_t off = offsets[top]; off < offsets[top + 1]; ++off) {
                        const uint32_t t = targets[off];
                        if (++arrived[t] == indegree[t]) stk.push_back(t);
                    }
                }
            }
        } else if (order == "lifo") {
            // gsim-style: LIFO stack, sources pushed ascending atom id,
            // successors pushed ascending atom id.
            std::vector<uint32_t> stack;
            for (uint32_t atom = 0; atom < n; ++atom)
                if (indegree[atom] == 0) stack.push_back(atom);
            std::vector<uint32_t> arrived(n, 0);
            while (!stack.empty()) {
                const uint32_t top = stack.back();
                stack.pop_back();
                atomOfRid.push_back(top);
                for (uint32_t off = offsets[top]; off < offsets[top + 1]; ++off) {
                    const uint32_t t = targets[off];
                    if (++arrived[t] == indegree[t]) stack.push_back(t);
                }
            }
        } else {
            std::cerr << "unknown order " << order << "\n";
            return 1;
        }
    }
    if (atomOfRid.size() != n) {
        std::cerr << "cyclic atom graph\n";
        return 1;
    }
    std::vector<uint32_t> ridOfAtom(n, 0);
    for (uint32_t rid = 0; rid < n; ++rid) ridOfAtom[atomOfRid[rid]] = rid;

    // rid-space adjacency (sorted unique)
    std::vector<uint32_t> member(n, 1);
    std::vector<uint64_t> edges;
    edges.reserve(targets.size());
    std::vector<std::vector<uint32_t>> nexts(n), prevs(n);
    for (uint32_t atom = 0; atom < n; ++atom) {
        const uint32_t s = ridOfAtom[atom];
        for (uint32_t off = offsets[atom]; off < offsets[atom + 1]; ++off) {
            const uint32_t t = ridOfAtom[targets[off]];
            edges.push_back((static_cast<uint64_t>(s) << 32) | t);
            nexts[s].push_back(t);
            prevs[t].push_back(s);
        }
    }
    for (uint32_t rid = 0; rid < n; ++rid) {
        std::sort(nexts[rid].begin(), nexts[rid].end());
        nexts[rid].erase(std::unique(nexts[rid].begin(), nexts[rid].end()), nexts[rid].end());
        std::sort(prevs[rid].begin(), prevs[rid].end());
        prevs[rid].erase(std::unique(prevs[rid].begin(), prevs[rid].end()), prevs[rid].end());
    }

    // ---- coarsening sweeps (exact port) --------------------------------
    std::vector<uint8_t> alive(n, 1);
    std::vector<uint32_t> parent(n, 0);
    std::iota(parent.begin(), parent.end(), uint32_t{0});
    std::size_t out1 = 0, in1 = 0, sib = 0;
    if (coarsen) {
        for (uint32_t s = n; s-- > 0;) {
            std::vector<uint32_t> &ns = nexts[s];
            if (ns.size() != 1) continue;
            const uint32_t t = ns.front();
            if (member[t] > coarsenBudget) continue;
            std::vector<uint32_t> &pt = prevs[t];
            sortedErase(pt, s);
            for (const uint32_t p : prevs[s]) {
                sortedErase(nexts[p], s);
                sortedInsert(nexts[p], t);
            }
            sortedUnionInto(pt, prevs[s]);
            member[t] += member[s];
            member[s] = 0;
            alive[s] = 0;
            parent[s] = t;
            ns.clear();
            prevs[s].clear();
            ++out1;
        }
        for (uint32_t s = 0; s < n; ++s) {
            if (alive[s] == 0) continue;
            std::vector<uint32_t> &sp = prevs[s];
            if (sp.size() != 1) continue;
            const uint32_t p = sp.front();
            if (member[p] > coarsenBudget) continue;
            std::vector<uint32_t> &np = nexts[p];
            sortedErase(np, s);
            for (const uint32_t d : nexts[s]) {
                sortedErase(prevs[d], s);
                sortedInsert(prevs[d], p);
            }
            sortedUnionInto(np, nexts[s]);
            member[p] += member[s];
            member[s] = 0;
            alive[s] = 0;
            parent[s] = p;
            sp.clear();
            nexts[s].clear();
            ++in1;
        }
        std::vector<uint32_t> candidates;
        candidates.reserve(n);
        for (uint32_t s = 0; s < n; ++s)
            if (alive[s] != 0 && !prevs[s].empty()) candidates.push_back(s);
        std::sort(candidates.begin(), candidates.end(), [&](uint32_t lhs, uint32_t rhs) {
            return prevs[lhs] != prevs[rhs] ? prevs[lhs] < prevs[rhs] : lhs < rhs;
        });
        std::size_t begin = 0;
        while (begin < candidates.size()) {
            std::size_t end = begin + 1;
            while (end < candidates.size() && prevs[candidates[end]] == prevs[candidates[begin]]) ++end;
            if (end - begin >= 2) {
                uint32_t host = candidates[begin];
                for (std::size_t index = begin + 1; index < end; ++index) {
                    const uint32_t s = candidates[index];
                    if (member[host] < siblingCap) {
                        member[host] += member[s];
                        member[s] = 0;
                        alive[s] = 0;
                        parent[s] = host;
                        ++sib;
                    } else {
                        host = s;
                    }
                }
            }
            begin = end;
        }
    }

    // ---- cluster adjacency rebuild -------------------------------------
    const auto findRoot = [&parent](uint32_t value) {
        uint32_t root = value;
        while (parent[root] != root) root = parent[root];
        while (parent[value] != root) {
            const uint32_t nx = parent[value];
            parent[value] = root;
            value = nx;
        }
        return root;
    };
    std::vector<std::vector<uint32_t>>().swap(nexts);
    std::vector<std::vector<uint32_t>>().swap(prevs);
    std::vector<uint64_t> mapped;
    mapped.reserve(edges.size());
    for (const uint64_t e : edges) {
        const uint32_t s = findRoot(static_cast<uint32_t>(e >> 32));
        const uint32_t t = findRoot(static_cast<uint32_t>(e));
        if (s != t) mapped.push_back((static_cast<uint64_t>(s) << 32) | t);
    }
    std::vector<uint64_t>().swap(edges);
    std::sort(mapped.begin(), mapped.end());
    mapped.erase(std::unique(mapped.begin(), mapped.end()), mapped.end());
    std::vector<uint32_t> outOff(n + 1, 0);
    for (const uint64_t e : mapped) ++outOff[static_cast<uint32_t>(e >> 32) + 1];
    std::partial_sum(outOff.begin(), outOff.end(), outOff.begin());
    std::vector<uint32_t> outTgt(mapped.size());
    std::vector<uint32_t> inDeg(n, 0);
    {
        std::vector<uint32_t> cursor(outOff.begin(), outOff.end() - 1);
        for (const uint64_t e : mapped) {
            const uint32_t t = static_cast<uint32_t>(e);
            outTgt[cursor[static_cast<uint32_t>(e >> 32)]++] = t;
            ++inDeg[t];
        }
    }

    // ---- resort (LIFO Kahn) --------------------------------------------
    const uint32_t liveCount = static_cast<uint32_t>(std::count(alive.begin(), alive.end(), 1));
    std::vector<uint32_t> seq;
    seq.reserve(liveCount);
    {
        std::vector<uint32_t> stack;
        for (uint32_t rid = 0; rid < n; ++rid)
            if (alive[rid] != 0 && inDeg[rid] == 0) stack.push_back(rid);
        std::vector<uint32_t> arrived(n, 0);
        while (!stack.empty()) {
            const uint32_t top = stack.back();
            stack.pop_back();
            seq.push_back(top);
            for (uint32_t off = outOff[top]; off < outOff[top + 1]; ++off) {
                const uint32_t t = outTgt[off];
                if (++arrived[t] == inDeg[t]) stack.push_back(t);
            }
        }
    }
    const uint32_t clusterCount = static_cast<uint32_t>(seq.size());
    std::vector<uint32_t> posOfRid(n, std::numeric_limits<uint32_t>::max());
    for (uint32_t pos = 0; pos < clusterCount; ++pos) posOfRid[seq[pos]] = pos;

    // cluster-DAG density + wire length of the resort sequence
    {
        uint64_t wireLen = 0;
        for (const uint64_t e : mapped) {
            const uint32_t ps = posOfRid[static_cast<uint32_t>(e >> 32)];
            const uint32_t pt = posOfRid[static_cast<uint32_t>(e)];
            wireLen += pt > ps ? pt - ps : 0;
        }
        std::cerr << "  [lab] clusterDAG edges=" << mapped.size()
                  << " clusters=" << clusterCount
                  << " deg=" << (clusterCount ? double(mapped.size()) / clusterCount : 0.0)
                  << " wireLen=" << wireLen
                  << " wire/cluster=" << (clusterCount ? double(wireLen) / clusterCount : 0.0) << "\n";
    }

    // ---- Kernighan DP ---------------------------------------------------
    std::vector<uint32_t> sizes(clusterCount), outDeg(clusterCount);
    std::vector<uint32_t> prevOff(clusterCount + 1, 0);
    for (uint32_t pos = 0; pos < clusterCount; ++pos) {
        const uint32_t rid = seq[pos];
        sizes[pos] = member[rid];
        outDeg[pos] = outOff[rid + 1] - outOff[rid];
    }
    std::vector<uint32_t> inNei(clusterCount, 0);
    for (const uint64_t e : mapped) ++inNei[posOfRid[static_cast<uint32_t>(e)]];
    for (uint32_t pos = 0; pos < clusterCount; ++pos) prevOff[pos + 1] = prevOff[pos] + inNei[pos];
    std::vector<uint32_t> prevPos(prevOff.back());
    {
        std::vector<uint32_t> cursor(prevOff.begin(), prevOff.end() - 1);
        for (const uint64_t e : mapped) {
            const uint32_t s = posOfRid[static_cast<uint32_t>(e >> 32)];
            const uint32_t t = posOfRid[static_cast<uint32_t>(e)];
            prevPos[cursor[t]++] = s;
        }
    }
    for (uint32_t pos = 0; pos < clusterCount; ++pos)
        std::sort(prevPos.begin() + prevOff[pos], prevPos.begin() + prevOff[pos + 1]);

    constexpr double kInf = std::numeric_limits<double>::infinity();
    std::vector<double> best(static_cast<std::size_t>(clusterCount) + 1, kInf);
    std::vector<uint32_t> back(static_cast<std::size_t>(clusterCount) + 1, 0);
    best[0] = 0.0;
    for (uint32_t i = 0; i < clusterCount; ++i) {
        if (best[i] == kInf) continue;
        uint32_t nextBound = i + 1;
        std::size_t accumulated = sizes[i];
        while (nextBound < clusterCount && accumulated + sizes[nextBound] <= cap) {
            accumulated += sizes[nextBound];
            ++nextBound;
        }
        int64_t cutCost = 0;
        for (uint32_t j = i + 1; j <= nextBound; ++j) {
            cutCost += outDeg[j - 1];
            const auto first = std::lower_bound(prevPos.begin() + prevOff[j - 1],
                                                prevPos.begin() + prevOff[j], i);
            cutCost -= static_cast<int64_t>(prevPos.begin() + prevOff[j] - first);
            const double candidate = best[i] + static_cast<double>(cutCost) + penalty;
            if (best[j] > candidate) {
                best[j] = candidate;
                back[j] = i;
            }
        }
    }
    std::vector<uint32_t> segmentOfPos(clusterCount, 0);
    uint32_t blockCount = 0;
    if (clusterCount != 0) {
        std::vector<uint32_t> cuts;
        cuts.push_back(clusterCount);
        for (uint32_t idx = clusterCount; back[idx] != 0;) {
            idx = back[idx];
            cuts.push_back(idx);
        }
        std::reverse(cuts.begin(), cuts.end());
        uint32_t begin = 0;
        for (const uint32_t end : cuts) {
            ++blockCount;
            for (uint32_t pos = begin; pos < end; ++pos) segmentOfPos[pos] = blockCount;
            begin = end;
        }
    }

    // ---- atom -> block, metrics ----------------------------------------
    std::vector<uint32_t> atomBlock(n, 0);
    for (uint32_t atom = 0; atom < n; ++atom)
        atomBlock[atom] = segmentOfPos[posOfRid[findRoot(ridOfAtom[atom])]];

    std::size_t crossing = 0;
    std::size_t importPairs = 0;
    if (repCopies == 0) {
        const auto instrAtom = loadNpy<uint32_t>(dir + "/instr_atom.npy");
        const auto stateWrite = loadNpy<uint8_t>(dir + "/instr_state_write.npy");
        const auto duSrc = loadNpy<uint32_t>(dir + "/du_src.npy");
        const auto duDst = loadNpy<uint32_t>(dir + "/du_dst.npy");
        const auto duVar = loadNpy<uint32_t>(dir + "/du_var.npy");
        // distinct crossing values (compute-network 口径: consumer not state-write)
        std::vector<uint8_t> seen;
        std::size_t varCount = 0;
        for (const uint32_t v : duVar) varCount = std::max(varCount, static_cast<std::size_t>(v) + 1);
        seen.assign(varCount, 0);
        std::vector<uint64_t> pairs;
        pairs.reserve(1u << 20);
        for (std::size_t e = 0; e < duSrc.size(); ++e) {
            if (stateWrite[duDst[e]] != 0) continue;
            const uint32_t bs = atomBlock[instrAtom[duSrc[e]]];
            const uint32_t bd = atomBlock[instrAtom[duDst[e]]];
            if (bs == bd) continue;
            if (seen[duVar[e]] == 0) {
                seen[duVar[e]] = 1;
                ++crossing;
            }
            pairs.push_back((static_cast<uint64_t>(bd) << 32) | duVar[e]);
        }
        std::sort(pairs.begin(), pairs.end());
        importPairs = std::unique(pairs.begin(), pairs.end()) - pairs.begin();
    }
    // atom-level crossing: atoms with any successor in a different block.
    // Exact match for the instruction-level metric when 1 atom = 1 root var
    // (holds for tree atoms; comb-loop SCC atoms are absent in this graph),
    // and the only available 口径 once absorption rewires the atom graph.
    std::size_t crossingAtomLevel = 0;
    for (uint32_t s = 0; s < n; ++s)
        for (uint32_t o = offsets[s]; o < offsets[s + 1]; ++o)
            if (atomBlock[s] != atomBlock[targets[o]]) {
                ++crossingAtomLevel;
                break;
            }
    if (repCopies != 0) crossing = crossingAtomLevel;

    // block size distribution
    std::vector<uint32_t> blockSize(blockCount + 1, 0);
    for (uint32_t atom = 0; atom < n; ++atom) ++blockSize[atomBlock[atom]];
    std::size_t mass = 0;
    for (uint32_t b = 1; b <= blockCount; ++b) mass += blockSize[b];

    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now() - t0).count();
    std::cout << "order=" << order << " cap=" << cap << " coarsenBudget=" << (coarsen ? coarsenBudget : 0)
              << " penalty=" << penalty << "\n"
              << "  merges out1=" << out1 << " in1=" << in1 << " sib=" << sib
              << " clusters=" << clusterCount << " blocks=" << blockCount
              << " avgSize=" << (blockCount ? static_cast<double>(mass) / blockCount : 0.0) << "\n"
              << "  cross_values_compute_network=" << crossing
              << " cross_atom_level=" << crossingAtomLevel
              << " import_pairs=" << importPairs << " elapsed_ms=" << ms << "\n";
    return 0;
}

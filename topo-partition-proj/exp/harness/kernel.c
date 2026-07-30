/* Segment-DP kernel for the Phase-1 searcher (D6: hot loop in C, ctypes bridge).
 *
 * Straight port of exp/harness/searcher.py:segment_dp (itself a port of the
 * production DP, wolvrix/lib/grhsim/am/activity_schedule.cpp:535-615) with the
 * Phase-1 cost formula: each segment pays, per distinct consumed value not
 * defined inside the segment, weight[var] copies; values with no producer in
 * the permutable set are permanent boundaries (paid in every consuming
 * segment, never subtracted). No per-segment penalty. Capacity in nodes.
 *
 * All buffers are owned by the caller; the function is scratch-only and
 * single-threaded. Scratch sizes: src_pos/seen/counted = nvar, dp/prev = n+1.
 * order[i] is the node at position i. The caller replays segment starts from
 * prev[] when it needs the cuts.
 *
 * seen/counted are stamp arrays: position `end` uses stamp (stamp_base + end).
 * The caller must pass a stamp_base that keeps every stamp of this call
 * strictly greater than any stamp left in seen/counted by earlier calls
 * (e.g. accumulate n+1 per call, re-zeroing the arrays on overflow).
 */

#include <float.h>
#include <stdint.h>

double segdp_cost(int32_t n, int32_t nvar, int32_t capacity,
                  const int32_t *use_off, const int32_t *use_var,
                  const int32_t *def_off, const int32_t *def_var,
                  const int64_t *weight,
                  int32_t *src_pos, uint32_t *seen, uint32_t *counted,
                  double *dp, int32_t *prev,
                  const int32_t *order, uint32_t stamp_base,
                  double segment_penalty) {
    for (int32_t var = 0; var < nvar; ++var) {
        src_pos[var] = -1;
    }
    for (int32_t pos = 0; pos < n; ++pos) {
        const int32_t node = order[pos];
        for (int32_t off = def_off[node]; off < def_off[node + 1]; ++off) {
            src_pos[def_var[off]] = pos;
        }
    }
    dp[0] = 0.0;
    for (int32_t end = 1; end <= n; ++end) {
        const uint32_t stamp = stamp_base + (uint32_t)end;
        double cost = 0.0;
        double best = DBL_MAX;
        int32_t best_start = end - 1;
        const int32_t floor = end - capacity > 0 ? end - capacity : 0;
        for (int32_t start = end - 1; start >= floor; --start) {
            const int32_t node = order[start];
            for (int32_t off = use_off[node]; off < use_off[node + 1]; ++off) {
                const int32_t var = use_var[off];
                if (seen[var] != stamp) {
                    seen[var] = stamp;
                    if (src_pos[var] < start) { /* -1: permanent boundary */
                        counted[var] = stamp;
                        cost += (double)weight[var];
                    }
                }
            }
            for (int32_t off = def_off[node]; off < def_off[node + 1]; ++off) {
                const int32_t var = def_var[off];
                if (counted[var] == stamp) {
                    counted[var] = 0;
                    cost -= (double)weight[var];
                }
            }
            const double candidate = dp[start] + cost + segment_penalty;
            if (candidate < best - 1e-12 ||
                (candidate - best <= 1e-12 && candidate - best >= -1e-12 &&
                 (end - start) > (end - best_start))) {
                best = candidate;
                best_start = start;
            }
        }
        dp[end] = best;
        prev[end] = best_start;
    }
    return dp[n];
}

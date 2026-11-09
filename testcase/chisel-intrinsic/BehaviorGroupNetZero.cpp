#include "grhsim_BehaviorGroupFixture.hpp"
#include <cstdio>

int main() {
    GrhSIM_BehaviorGroupFixture model;
    model.init();
    model.reset = true;
    model.clock = false; model.eval();
    model.clock = true; model.eval();
    model.clock = false;
    model.reset = false;
    model.io_valid_0 = model.io_valid_2 = true;
    model.io_kind_0 = model.io_kind_2 = 1;
    model.io_index_0 = model.io_index_2 = 5;
    model.io_data_0 = 1;
    model.io_data_2 = 0;
    model.eval();
    model.reset_perf_counters();
    for (int cycle = 0; cycle < 100; ++cycle) {
        model.clock = true; model.eval(); model.eval();
        model.clock = false; model.eval();
        if (model.io_snapshot_0_5 != 0) return 1;
    }
    const auto counters = model.perf_counters();
    if (counters.behaviorGroupCommits != 100 || counters.behaviorEnabledUpdates != 200 ||
        counters.behaviorTouchedRows != 100 || counters.touchedWriteCount != 0 ||
        counters.scheduledMemoryReads != 0) return 2;
    puts("PASS: 100 commits, 200 writes, zero net changes and zero reader reevaluations");
}

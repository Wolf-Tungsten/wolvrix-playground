#include <array>
#include <bit>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "VRef.h"
#include "grhsim_xs_bugcase_tb.hpp"
#include "verilated.h"

namespace {

struct Stimulus {
    std::string name = "trace_cycle_10286";
    std::uint8_t hits = 0x10;
    std::uint32_t entry_target = 0x13b5;
    std::uint64_t expected_target = 0x800013b5;
    std::uint8_t entry_position = 26;
    std::uint8_t prediction_position = 26;
    std::uint8_t entry_branch_type = 3;
    std::uint8_t prediction_branch_type = 3;
    std::uint8_t entry_ras = 2;
    std::uint8_t prediction_ras = 2;
    bool t1_fire = true;
    std::uint8_t bank_mask = 1;
};

template <typename Model>
void drive(Model& model, const Stimulus& s) {
    model.hits = s.hits;
    model.entry_target = s.entry_target;
    model.expected_target = s.expected_target;
    model.entry_position = s.entry_position;
    model.prediction_position = s.prediction_position;
    model.entry_branch_type = s.entry_branch_type;
    model.prediction_branch_type = s.prediction_branch_type;
    model.entry_ras = s.entry_ras;
    model.prediction_ras = s.prediction_ras;
    model.t1_fire = s.t1_fire;
    model.bank_mask = s.bank_mask;
}

std::vector<Stimulus> stimuli() {
    std::vector<Stimulus> result(1);
    constexpr std::array<std::uint32_t, 6> targets = {0, 1, 2, 3, 0x13b5, 0x3fffff};
    for (unsigned way = 0; way < 8; ++way) {
        for (auto target : targets) {
            Stimulus s;
            s.name = "equal_way_" + std::to_string(way) + "_target_" + std::to_string(target);
            s.hits = static_cast<std::uint8_t>(1u << way);
            s.entry_target = target;
            s.expected_target = 0x80000000 | target;
            result.push_back(s);
        }
        for (unsigned low = 0; low < 2; ++low) {
            Stimulus s;
            s.name = "high_bit_difference_way_" + std::to_string(way) + "_low_" + std::to_string(low);
            s.hits = static_cast<std::uint8_t>(1u << way);
            s.entry_target = 2 | low;
            s.expected_target = 0x80000000 | low;
            result.push_back(s);
        }
    }
    Stimulus s;
    s.name = "no_hit";
    s.hits = 0;
    result.push_back(s);
    s = Stimulus{};
    s.name = "position_mismatch";
    s.entry_position = 25;
    result.push_back(s);
    s = Stimulus{};
    s.name = "ras_mismatch";
    s.entry_ras = 0;
    result.push_back(s);
    s = Stimulus{};
    s.name = "branch_type_mismatch";
    s.entry_branch_type = 1;
    result.push_back(s);
    s = Stimulus{};
    s.name = "non_indirect_branch";
    s.entry_branch_type = s.prediction_branch_type = 1;
    result.push_back(s);
    s = Stimulus{};
    s.name = "train_fire_disabled";
    s.t1_fire = false;
    result.push_back(s);
    s = Stimulus{};
    s.name = "bank0_disabled";
    s.bank_mask = 2;
    result.push_back(s);
    return result;
}

} // namespace

double sc_time_stamp() { return 0; }

int main(int argc, char** argv) {
    const bool expectMismatch = argc == 2 && std::string(argv[1]) == "--expect-mismatch";
    Verilated::commandArgs(argc, argv);
    VRef ref;
    GrhSIM_xs_bugcase_tb grhsim;
    grhsim.init();
    std::ofstream csv("results.csv");
    csv << "name,hits,target,expected_low22,ref_hit,grhsim_hit,ref_selected,grhsim_selected,"
           "ref_need_correct,grhsim_need_correct,ref_write_bank0,grhsim_write_bank0\n";

    unsigned mismatches = 0;
    unsigned errors = 0;
    bool traceReproduced = false;
    bool traceMatched = false;
    const auto vectors = stimuli();
    for (const auto& s : vectors) {
        drive(ref, s);
        drive(grhsim, s);
        ref.eval();
        grhsim.eval();
        const bool hit = s.hits != 0 && s.entry_position == s.prediction_position &&
                         s.entry_branch_type == s.prediction_branch_type && s.entry_ras == s.prediction_ras;
        const unsigned selected = hit ? 1u << std::countr_zero(static_cast<unsigned>(s.hits)) : 0;
        const bool correct = hit && s.prediction_branch_type == 3 &&
                             s.entry_target != (s.expected_target & 0x3fffff);
        const bool write = correct && s.t1_fire && (s.bank_mask & 1);
        if (ref.out_hit != hit || ref.out_selected != selected || ref.out_need_correct != correct ||
            ref.out_write_bank0 != write || grhsim.out_hit != hit || grhsim.out_selected != selected) {
            std::fprintf(stderr, "[ERROR] %s reference/oracle or hit-selection disagreement\n", s.name.c_str());
            ++errors;
        }
        const bool mismatch = ref.out_need_correct != grhsim.out_need_correct ||
                              ref.out_write_bank0 != grhsim.out_write_bank0;
        if (mismatch) {
            ++mismatches;
            if (mismatches <= 12) {
                std::printf("[MISMATCH] %s selected=0x%02x target=0x%06x expected_low22=0x%06x "
                            "needCorrectTarget ref=%u grhsim=%u writeBank0 ref=%u grhsim=%u\n",
                            s.name.c_str(), selected, s.entry_target,
                            static_cast<unsigned>(s.expected_target & 0x3fffff),
                            unsigned(ref.out_need_correct), unsigned(grhsim.out_need_correct),
                            unsigned(ref.out_write_bank0), unsigned(grhsim.out_write_bank0));
            }
        }
        if (s.name == "trace_cycle_10286") {
            traceReproduced = !ref.out_need_correct && grhsim.out_need_correct &&
                              !ref.out_write_bank0 && grhsim.out_write_bank0;
            traceMatched = !mismatch;
        }
        if (!hit || s.prediction_branch_type != 3) {
            if (grhsim.out_need_correct || grhsim.out_write_bank0) {
                ++errors;
            }
        }
        csv << s.name << ',' << unsigned(s.hits) << ',' << s.entry_target << ','
            << (s.expected_target & 0x3fffff) << ',' << unsigned(ref.out_hit) << ','
            << unsigned(grhsim.out_hit) << ',' << unsigned(ref.out_selected) << ','
            << unsigned(grhsim.out_selected) << ',' << unsigned(ref.out_need_correct) << ','
            << unsigned(grhsim.out_need_correct) << ',' << unsigned(ref.out_write_bank0) << ','
            << unsigned(grhsim.out_write_bank0) << '\n';
    }
    ref.final();
    if (!csv) {
        std::fprintf(stderr, "[ERROR] failed to write results.csv\n");
        ++errors;
    }
    std::printf("[SUMMARY] vectors=%zu mismatches=%u reference_or_control_errors=%u trace_10286=%s\n",
                vectors.size(), mismatches, errors,
                traceReproduced ? "reproduced" : traceMatched ? "matched" : "unexpected");
    if (expectMismatch) {
        if (errors != 0 || !traceReproduced) {
            return 1;
        }
        std::puts("[REPRODUCED] isolated AheadBtb target correction differs from Verilator");
        return 0;
    }
    if (errors == 0 && mismatches == 0) {
        std::puts("[PASS] isolated AheadBtb target correction matches Verilator");
    }
    return errors != 0 || mismatches != 0 ? 1 : 0;
}

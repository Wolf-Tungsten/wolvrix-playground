"""Wrapper-only cycle instrumentation shared by build flows."""
import re

SUFFIXES = ("common", "load_0", "eval_0", "update_0")

def instrument(text, suffix):
    text = '#include "repcut_cycle_trace.hpp"\n' + text
    if suffix == "common":
        # This full-cycle recorder currently supports the flat three-phase
        # package only. Do not silently misattribute early-phase callbacks.
        for field in ("early_eval_step_fns_", "early_update_step_fns_"):
            assert f"{field}.reserve(0);" in text, field
        needle = "  const auto stepBegin = WolviClock::now();"
        assert text.count(needle) == 1
        text = text.replace(needle,
            "  repcut_cycle_trace::begin(step_count_, top_in_clock_, top_in_reset_);\n" + needle)
        needle = "  step_timing_.total_ns += elapsed_ns_(stepBegin, finalUpdateEnd);"
        assert text.count(needle) == 1
        text = text.replace(needle, needle + "\n  repcut_cycle_trace::finish(\n"
            "      elapsed_ns_(inputLoadBegin, inputLoadEnd),\n"
            "      elapsed_ns_(earlyEvalBegin, earlyEvalEnd) + elapsed_ns_(normalEvalBegin, normalEvalEnd),\n"
            "      elapsed_ns_(earlyUpdateBegin, earlyUpdateEnd) + elapsed_ns_(finalUpdateBegin, finalUpdateEnd));")
        return text
    fn, begin, end, phase = {
        "load_0": ("load", "inputApplyBegin", "inputApplyEnd", 0),
        "eval_0": ("eval", "evalBegin", "evalEnd", 1),
        "update_0": ("update_final", "updatePushBegin", "updatePushEnd", 2),
    }[suffix]
    found = []

    def replace(match):
        part = int(match[1])
        body = match[0]
        needle = f"  partTimingStats->total_ns += elapsed_ns_({begin}, {end});"
        assert body.count(needle) == 1, (suffix, part)
        found.append(part)
        return body.replace(needle, needle +
            f"\n  repcut_cycle_trace::record({part}, {phase}, elapsed_ns_({begin}, {end}));")

    text = re.sub(rf"void WolviRepCutGrhSimSim::run_{fn}_part_(\d+)_\([^\n]+\) \{{.*?\n\}}",
                  replace, text, flags=re.S)
    assert sorted(found) == list(range(32)), (suffix, found)
    return text

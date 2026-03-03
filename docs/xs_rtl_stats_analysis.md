# XiangShan RTL Stats Analysis (Wolvrix)

Data source: `tmp/wolvrix_xs_stats.json` (stats JSON extracted from the Wolvrix `stats` pass).

## Scale Summary
- Operations: 5,778,793
- Values: 5,134,133
- Total value bitwidth: 87,974,960 bits
- Register bitwidth total: 4,550,129 bits (~0.54 MiB)
- Latch bitwidth total: 410 bits
- Memory port data bitwidth total: 1,658,774 bits (~0.20 MiB)
- Memory capacity total: 191,387,240 bits (~22.8 MiB)

## Operation Mix (Top 12)
| Operation | Count | Share |
| --- | --- | --- |
| kMux | 1,011,757 | 17.51% |
| kAnd | 839,072 | 14.52% |
| kOr | 668,512 | 11.57% |
| kLogicAnd | 383,317 | 6.63% |
| kRegister | 310,989 | 5.38% |
| kRegisterWritePort | 310,989 | 5.38% |
| kRegisterReadPort | 310,923 | 5.38% |
| kAssign | 296,197 | 5.13% |
| kSliceDynamic | 284,590 | 4.92% |
| kEq | 275,727 | 4.77% |
| kConcat | 257,255 | 4.45% |
| kLogicOr | 234,469 | 4.06% |

Observation: control logic dominates (mux/and/or/logic operations are the largest share), and dynamic slicing is non-trivial, indicating frequent indexed bit/field access.

## Value Width Distribution
Top widths (values):
- 1-bit: 3,245,811 (63.22%)
- 2-bit: 435,976 (8.49%)
- 64-bit: 340,261 (6.63%)
- 8-bit: 202,914 (3.95%)
- 16-bit: 28,891 (0.56%)
- 32-bit: 27,620 (0.54%)

Interpretation: the design is control-heavy (1-2 bit values dominate), while 64-bit datapath elements remain a significant slice.

## State Elements
### Registers and Latches
- Registers: 310,989
- Register read ports: 310,923
- Register write ports: 310,989
- Average register width: ~14.6 bits
- Register bitwidth total: 4,550,129 bits (~0.54 MiB)
- Latch bitwidth total: 410 bits

Top register widths:
- 1-bit: 39.79%
- 2-bit: 17.32%
- 64-bit: 15.02%

Latches are negligible (410 total), suggesting the RTL is largely edge-triggered.

### Memories
- Memories: 4,809
- Memory read ports: 889
- Memory write ports: 4,184 (write ports are ~4.7x read ports)
- Average memory width: ~48.9 bits
- Memory width distribution: 32-bit memories are dominant (3,999, 83.16%)
- Median memory width: 32 bits, p90: 64 bits, p99: 345 bits

Capacity:
- Total capacity: 191,387,240 bits (~22.8 MiB)
- Average capacity: ~39,798 bits (~4.86 KiB)
- Approximate average depth: ~815 entries (derived from average capacity / average width)

Memory ports are wide overall:
- Total port data bitwidth: 1,658,774 bits
- Average data width per port: ~327 bits

## Combinational Structure and Dataflow
Writeport cone statistics (631,166 roots analyzed):
- Cone depth: median 17, p90 65, p99 97, mean 27.84
- Cone size: median 120 ops, p90 2,744 ops, p99 7,243 ops, mean 958.44

This indicates deep and wide combinational logic feeding state updates, with a long tail of very large cones.

## Fanout Characteristics
- Combinational op fanout (sinks): median 2, p90 86, max 512,803
- Readport fanout (sinks): median 9, p90 2,437, max 126,931

The extremely high maxima suggest global control nets (e.g., resets, enables, or widely-broadcast signals).

## RTL Characteristics Summary
- **Control-dominant logic**: mux/and/or/logic operations lead; 1-bit values exceed 60%.
- **Mixed datapath widths**: 64-bit values and registers are a material share alongside dense 1-2 bit control.
- **Edge-triggered design**: latches are almost absent; register read/write ports align closely with register count.
- **Memory profile**: many 32-bit memories with a long tail of wide memories; total capacity is large (~22.8 MiB).
- **Deep state update logic**: large writeport cones point to complex next-state computations.
- **High-fanout nets**: heavy broadcast behavior in both combinational and readport domains.

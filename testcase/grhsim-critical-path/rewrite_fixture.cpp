#include "Vrewrite_fixture.h"
#include "verilated.h"
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    VerilatedContext context;
    Vrewrite_fixture dut(&context);
    std::ifstream stimulus(argv[1]);
    std::string line;
    unsigned expected = 0;
    while (std::getline(stimulus, line)) {
        unsigned cycle, a, reset;
        if (std::sscanf(line.c_str(), "{\"cycle\":%u,\"inputs\":{\"a\":%u,\"reset\":%u}}", &cycle, &a, &reset) != 3 ||
            cycle != expected++ || a > 255 || reset > 1) return 3;
        dut.clock = 0; dut.a = a; dut.reset = reset; dut.eval();
        dut.clock = 1; dut.eval();
        std::cout << "{\"cycle\":" << cycle << ",\"inputs\":{\"a\":" << a << ",\"reset\":" << reset
                  << "},\"outputs\":{\"y\":" << unsigned(dut.y) << "},\"state\":{\"q\":" << unsigned(dut.q)
                  << "},\"commits\":[]}\n";
    }
    dut.final();
    return stimulus.eof() ? 0 : 4;
}

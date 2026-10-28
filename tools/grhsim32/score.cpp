// Score all portfolio assignments in one streaming pass over the full graph.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>

int main(int argc, char **argv)
{
    try
    {
        if (argc < 4) throw std::runtime_error("usage: score graph.hgr isolated_count assignment [...]");
        const auto isolated = std::stoul(argv[2]);
        std::ifstream graph(argv[1]);
        std::size_t edges, nodes, format, dimensions;
        if (!(graph >> edges >> nodes >> format >> dimensions)) throw std::runtime_error("cannot read graph");
        std::vector<std::vector<uint32_t>> labels(argc - 3, std::vector<uint32_t>(nodes));
        for (int i = 3; i < argc; ++i)
        {
            std::ifstream input(argv[i]);
            for (auto &label : labels[i - 3])
                if (!(input >> label)) throw std::runtime_error("cannot read assignment");
        }
        std::vector<uint64_t> costs(labels.size());
        std::string line;
        std::getline(graph, line);
        for (std::size_t edge = 0; edge < edges; ++edge)
        {
            if (!std::getline(graph, line)) throw std::runtime_error("cannot read edge");
            std::istringstream row(line);
            uint64_t weight;
            row >> weight;
            std::vector<uint64_t> parts(labels.size());
            uint32_t pin;
            while (row >> pin)
                for (std::size_t i = 0; i < labels.size(); ++i)
                    parts[i] |= uint64_t{1} << labels[i].at(pin - 1);
            for (std::size_t i = 0; i < parts.size(); ++i)
                costs[i] += weight * (__builtin_popcountll(parts[i]) - 1);
        }
        std::vector<std::vector<std::array<uint64_t, 6>>> loads(labels.size(),
            std::vector<std::array<uint64_t, 6>>(32));
        std::array<uint64_t, 6> totals{};
        for (std::size_t node = 0; node < nodes; ++node)
            for (std::size_t axis = 0; axis < 6; ++axis)
            {
                uint64_t weight;
                if (!(graph >> weight)) throw std::runtime_error("cannot read node weight");
                if (labels[0][node] >= isolated) totals[axis] += weight;
                for (std::size_t i = 0; i < labels.size(); ++i)
                    if (labels[i][node] >= isolated) loads[i].at(labels[i][node])[axis] += weight;
            }
        for (std::size_t i = 0; i < costs.size(); ++i)
        {
            bool feasible = true;
            for (std::size_t part = isolated; part < 32; ++part)
                for (std::size_t axis = 0; axis < 6; ++axis)
                {
                    const auto count = 32 - isolated;
                    const auto capacity = ((totals[axis] + count - 1) / count) * 105 / 100;
                    feasible &= loads[i][part][axis] <= capacity;
                }
            std::cout << i << ' ' << costs[i] << ' ' << feasible << '\n';
        }
    }
    catch (const std::exception &error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

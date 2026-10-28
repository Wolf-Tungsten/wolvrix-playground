#include "transform/repcut_assignment_model.hpp"
#include <filesystem>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>

using namespace wolvrix::lib::transform;

int main(int argc, char **argv)
{
    try
    {
        if (argc < 4 || argc % 2) throw std::runtime_error("usage: model.txtdata assignment prefix [...]");
        std::ifstream input(argv[1]); std::string version;
        std::getline(input, version);
        if (version != "repcut-assignment-model-v2") throw std::runtime_error("cache version mismatch");
        RepcutAssignmentModel model;
        std::getline(input, model.adapter);
        std::size_t features, pieces, values, owners;
        input >> model.atomCount >> features >> pieces >> values >> owners;
        if (!model.atomCount || !features || !pieces)
            throw std::runtime_error("empty assignment model");
        model.featureNames.resize(features);
        for (auto &name : model.featureNames) input >> name;
        model.pieces.resize(pieces);
        for (auto &piece : model.pieces)
        {
            std::size_t n; input >> n; piece.atoms.resize(n); piece.features.resize(features);
            for (auto &atom : piece.atoms) input >> atom;
            for (auto &feature : piece.features) input >> feature;
        }
        model.values.resize(values);
        for (auto &value : model.values)
        {
            std::size_t n;
            input >> value.key >> value.writerAtom >> value.width >> value.inferredOwner >> n;
            value.readerAtoms.resize(n);
            for (auto &atom : value.readerAtoms) input >> atom;
        }
        model.inferredOwners.resize(owners);
        for (auto &owner : model.inferredOwners)
        {
            std::size_t n; input >> n; owner.userAtoms.resize(n);
            for (auto &users : owner.userAtoms)
            {
                input >> n; users.resize(n);
                for (auto &atom : users) input >> atom;
            }
        }
        if (!input) throw std::runtime_error("truncated model");
        std::string trailing;
        if (input >> trailing) throw std::runtime_error("extra model data");
        RepcutAssignmentEvaluator evaluator(std::move(model));
        std::cout << "MODEL LOADED" << std::endl;
        std::vector<uint32_t> baselineAssignment;
        RepcutAssignmentReport baseline;
        uint32_t partitions = 0;
        for (int argument = 2; argument < argc; argument += 2)
        {
            std::ifstream file(argv[argument]);
            std::vector<uint32_t> assignment; uint32_t label;
            while (file >> label) assignment.push_back(label);
            if (!file.eof()) throw std::runtime_error("bad assignment");
            if (assignment.empty()) throw std::runtime_error("empty assignment");
            if (!partitions) partitions = *std::max_element(assignment.begin(), assignment.end()) + 1;
            const auto report = evaluator.evaluate(assignment, partitions);
            if (argument == 2) { baselineAssignment = assignment; baseline = report; }
            const auto affected = repcutAssignmentDirectImpact(baselineAssignment, baseline, assignment, report);
            std::ofstream impact(std::string(argv[argument+1]) + ".impact.txt");
            for (auto part : affected) impact << part << '\n';
            std::ofstream parts(std::string(argv[argument+1]) + ".parts.csv");
            parts << "part";
            for (const auto &feature : evaluator.model().featureNames) parts << ',' << feature;
            parts << ",piece_copies,send_calls,send_scalar_calls,send_wide_calls,send_bytes,send_full64_blocks,send_tail_calls,send_tail_bytes,send_peers,receive_calls,receive_bytes,receive_peers\n";
            for (std::size_t p = 0; p < report.parts.size(); ++p)
            {
                const auto &r = report.parts[p]; parts << p;
                for (auto f : r.features) parts << ',' << f;
                parts << ',' << r.pieceCopies << ',' << r.sent.calls << ',' << r.sent.scalarCalls << ',' << r.sent.wideCalls
                      << ',' << r.sent.storageBytes << ',' << r.sent.full64ByteBlocks << ',' << r.sent.tailCalls
                      << ',' << r.sent.tailBytes << ',' << r.sendPeers << ',' << r.received.calls << ','
                      << r.received.storageBytes << ',' << r.receivePeers << '\n';
            }
            std::ofstream transfers(std::string(argv[argument+1]) + ".transfers.csv");
            transfers << "owner,readers,width,members,storage_bytes,full64_blocks,tail_bytes\n";
            for (const auto &group : report.transfers)
            {
                transfers << group.ownerPart << ',';
                for (auto reader : group.readerParts) transfers << reader << ';';
                transfers << ',' << group.width << ',';
                for (const auto &m : group.members) transfers << m.key << ':' << m.width << ':' << m.lowBit << ';';
                transfers << ',' << group.perReader.storageBytes << ',' << group.perReader.full64ByteBlocks
                          << ',' << group.perReader.tailBytes << '\n';
            }
            if (!parts || !transfers || !impact) throw std::runtime_error("report write failed");
            std::cout << "ASSIGNMENT PASS " << argv[argument] << " calls=" << report.totalTransfers.calls
                      << " bytes=" << report.totalTransfers.storageBytes << std::endl;
        }
    }
    catch (const std::exception &e) { std::cerr << e.what() << std::endl; return 1; }
}

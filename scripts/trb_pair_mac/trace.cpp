// Sample mapped pin values immediately before each root-clock rising edge.
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

struct Signal {
    std::string value;
};
struct Bit {
    int signal;
    int offset;
    char constant;
};

int main(int argc, char** argv) {
    if (argc != 5) return 2;
    std::ifstream mapping(argv[1]), wave(argv[2]);
    std::string id, text;
    std::vector<Signal> signals;
    std::unordered_map<std::string, unsigned> lookup;
    int count, width, clock_index;
    long long begin, end;
    mapping >> count >> clock_index >> begin >> end;
    for (int i = 0; i < count; ++i) {
        mapping >> id >> width;
        lookup[id] = signals.size();
        signals.push_back({std::string(width, 'x')});
    }
    std::vector<Bit> bits;
    int signal, offset;
    char constant;
    while (mapping >> signal >> offset >> constant) bits.push_back({signal, offset, constant});
    std::ofstream output(argv[3]), edges(argv[4]);
    while (std::getline(wave, text) && text.find("$enddefinitions") == std::string::npos) {}
    long long time = 0;
    std::vector<std::pair<unsigned, std::string>> pending;
    auto flush = [&]() {
        char current = signals.at(clock_index).value[0], next = current;
        for (auto &change : pending)
            if (static_cast<int>(change.first) == clock_index) next = change.second[0];
        if (time >= begin && time < end && current == '0' && next == '1') {
            edges << time - begin << '\n';
            for (const auto &bit : bits)
                output.put(bit.signal < 0 ? bit.constant : signals[bit.signal].value[bit.offset]);
            output.put('\n');
        }
        for (auto &change : pending) {
            auto &value = signals[change.first].value;
            const auto &update = change.second;
            if (update.size() > value.size()) throw std::runtime_error("bad VCD width");
            const char pad = (update[0] == 'x' || update[0] == 'z') ? update[0] : '0';
            value.assign(value.size() - update.size(), pad);
            value += update;
        }
        pending.clear();
    };
    while (std::getline(wave, text)) {
        if (text.empty()) continue;
        if (text[0] == '#') {
            flush();
            time = std::stoll(text.substr(1));
            if (time >= end) break;
            continue;
        }
        unsigned char first = text[0];
        size_t split = 0;
        if (first == 'b' || first == 'B') {
            split = text.find(' ', 1);
            if (split == std::string::npos) continue;
            id.assign(text, split + 1, std::string::npos);
        } else if (first == '0' || first == '1' || first == 'x' || first == 'z') {
            id.assign(text, 1, std::string::npos);
        } else {
            continue;
        }
        auto match = lookup.find(id);
        if (match != lookup.end())
            pending.emplace_back(match->second, split ? text.substr(1, split - 1) : text.substr(0, 1));
    }
    flush();
    return 0;
}


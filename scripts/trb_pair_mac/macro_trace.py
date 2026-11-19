"""Extract the actual SRAM pin schedule from the existing 4x32 gate VCD."""
import json
import re
import subprocess

from common import BASE, REPORT, ROOT, WORK, write_json

PIN_WIDTH = {"CEN": 1, "GWEN": 1, "D": 16, "WEN": 16, "Q": 16}
KINDS = {"RAMSP128X16": 7, "RAMSP1024X16": 10, "RAMSP4096X16": 12}


def macro_pins(path):
    text = path.read_text()
    modules = {}
    for match in re.finditer(r"(?ms)^module\s+(\w+)\b(.*?)^endmodule", text):
        modules[match[1]] = [(item[1], item[2].lstrip("\\"), dict(re.findall(r"\.(\w+)\s*\(([^()]*)\)", item[3])))
                             for item in re.finditer(r"(?ms)^\s*(\w+)\s+(\S+)\s*\((.*?)\);", match[2])]
    macros = []

    def walk(module, scope):
        for ref, name, pins in modules[module]:
            child = scope + (name,)
            if ref in modules:
                walk(ref, child)
            elif ref in KINDS:
                if scope[-1] == "core":
                    role = name.split("_")[0]
                elif scope[-2:] == ("shared_memory", "memory"):
                    role = "shared"
                else:
                    continue
                macros.append(dict(role=role, name=name, scope=scope, ref=ref, pins=pins))

    walk("kwt_complete_soc", ("complete_soc_tb", "dut"))
    expected = {"shared": 64, "input": 8, "weight": 32, "result": 8}
    assert {role: sum(m["role"] == role for m in macros) for role in expected} == expected
    return macros


def declarations(stream):
    values, width = {}, {}
    scope = []
    for line in stream:
        fields = line.decode("ascii", errors="replace").split()
        if not fields:
            continue
        if fields[0] == "$scope":
            scope.append(fields[2].lstrip("\\"))
        elif fields[0] == "$upscope":
            scope.pop()
        elif fields[0] == "$var":
            size = int(fields[2])
            symbol, name = fields[3], fields[4].lstrip("\\")
            rng = re.fullmatch(r"\[(-?\d+)(?::(-?\d+))?\]", fields[5]) if len(fields) > 6 else None
            if rng:
                first = int(rng[1])
                last = int(rng[2] or rng[1])
                indices = list(range(first, last + (-1 if first >= last else 1), -1 if first >= last else 1))
            else:
                indices = list(reversed(range(size))) if size > 1 else [None]
            width[symbol] = size
            assert len(indices) == size, (scope, fields)
            for offset, index in enumerate(indices):
                values[tuple(scope), name, index] = (symbol, offset, "0")
            if size > 1:
                values[tuple(scope), name, "vector"] = [(symbol, offset, "0") for offset in range(size)]
        elif fields[0] == "$enddefinitions":
            break
    return values, width


def expression_bits(scope, expr, size, values):
    expr = re.sub(r"\s+", "", expr).lstrip("\\")
    if expr.startswith("{"):
        bits = [bit for part in expr[1:-1].split(",") for bit in expression_bits(scope, part, 1, values)]
        # Slices and explicitly sized constants inside a concatenation provide their own widths.
        return bits
    const = re.fullmatch(r"(\d+)'([bh])([0-9a-fxz]+)", expr, re.I)
    if const:
        n, fmt, val = int(const[1]), const[2].lower(), const[3].lower()
        if fmt == "h":
            val = format(int(val, 16), "b")
        return [(None, 0, bit) for bit in val.rjust(n, "0")]
    selection = re.fullmatch(r"(.+)\[(-?\d+)(?::(-?\d+))?\]", expr)
    if selection:
        name, first, last = selection[1], int(selection[2]), int(selection[3] or selection[2])
        step = -1 if first >= last else 1
        bits = []
        for index in range(first, last + step, step):
            key = scope, name, index
            if key not in values:
                key = scope, "%s[%d]" % (name, index), None
            bits.append(values[key])
        return bits
    if size == 1:
        key = scope, expr, None
        if key in values:
            return [values[key]]
        key = scope, expr, "vector"
        if key in values:
            return values[key]
        return [values[scope, expr, 0]]
    return [values[scope, expr, index] for index in reversed(range(size))]


def main():
    out = WORK / "macro_trace"
    out.mkdir(parents=True, exist_ok=True)
    screen = json.loads((BASE / "final-screen.json").read_text())
    cold = json.loads((BASE / "gate-power/vcd-window.json").read_text())
    netlist = ROOT / "build/server" / ("complete_soc_sm40_" + screen["tag"]) / "netlist.v"
    vcd = ROOT / cold["original"]
    macros = macro_pins(netlist)
    with vcd.open("rb") as stream:
        values, widths = declarations(stream)
    flat = []
    clocks = set()
    ordered = ("CEN", "GWEN", "A", "D", "WEN", "Q")
    for macro in macros:
        scope = tuple(macro["scope"])
        bits = []
        for pin in ordered:
            size = KINDS[macro["ref"]] if pin == "A" else PIN_WIDTH[pin]
            if pin == "Q" and pin not in macro["pins"]:
                bits.extend([(None, 0, "x")] * size)
                continue
            bit_list = expression_bits(scope, macro["pins"][pin], size, values)
            assert len(bit_list) == size, (macro["name"], pin, macro["pins"][pin])
            bits.extend(bit_list)
        macro["bits"] = len(bits)
        flat.extend(bits)
        clock, = expression_bits(scope, macro["pins"]["CLK"], 1, values)
        clocks.add(clock[0])
    clock, = clocks
    signals = {symbol: index for index, symbol in enumerate(dict.fromkeys(
        [clock] + [symbol for symbol, _, _ in flat if symbol is not None]))}
    mapping = out / "mapping.txt"
    with mapping.open("w") as stream:
        stream.write("%d %d %d %d\n" % (len(signals), signals[clock], cold["start_tick"], cold["end_tick"]))
        for symbol in signals:
            stream.write("%s %d\n" % (symbol, widths[symbol]))
        for symbol, offset, constant in flat:
            stream.write("%d %d %s\n" % (signals.get(symbol, -1), offset, constant))
    binary = out / "trace"
    subprocess.run(["g++", "-O3", "-std=c++11", str(ROOT/"scripts/trb_pair_mac/trace.cpp"), "-o", str(binary)],
                   check=True)
    subprocess.run([str(binary), str(mapping), str(vcd), str(out/"pins.txt"), str(out/"edges.txt")], check=True)
    edges = (out / "edges.txt").read_text().splitlines()
    assert len(edges) == 14344
    write_json(out/"macro-list.json", dict(tag=screen["tag"], cycles=len(edges), macros=macros))
    print("PAIR_MACRO_TRACE_READY", len(edges), len(macros), flush=True)


if __name__ == "__main__":
    main()


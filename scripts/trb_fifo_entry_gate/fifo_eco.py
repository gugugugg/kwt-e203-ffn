"""Gate the existing 17 FIFO data words in the accepted 4x32 netlist."""
import json
from collections import Counter
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/trb_param_word_gate"))
from eco import CORE, INSTANCE, connections, proof, render, split_ports

NAME = "ffn_trb_4x32_fifo_entry_gate"
PARENT = "ffn_trb_4x32_param_word_gate"
REPORT = ROOT / "reports/optimization" / NAME
BASE = REPORT.parent / PARENT
TAG = "opt_" + NAME + "_final_ss_ema2"
CHECKPOINT = ROOT / "build/server" / ("complete_soc_sm40_" + TAG)
BITS = 17 * 64
STATE = re.compile(r"out_word_reg_(\d+)__(\d+)_$")
ICG = "CLKLANAQV1_12TR40"
HOLD = "AOI22BBV0_12TR40"
DATA = "NAND2CV0_12TR40"


def rtl():
    source = (BASE / "kwt_threebank_core.sv").read_text()
    anchor = "    reg [63:0] out_word [0:16];"
    start = source.index("                out_word[out_tail]<=")
    end = source.index(";", start)
    value = source[start:end].split("<=", 1)[1]
    source = source[:start] + source[end + 2:]
    block = """    for (genvar entry=0; entry<17; entry++) begin: fifo_entries
        wire write_entry=rst_n&&busy&&pending_result&&out_tail==5'(entry);
        wire entry_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_entry),
            .test_enable(1'b0),.gated_clk(entry_clk));
        wire [63:0] entry_data=write_entry?""" + value + """:64'hffffffffffffffff;
        always @(posedge entry_clk) out_word[entry]<=entry_data;
    end
"""
    before = "    wire [6:0] output_credit"
    assert source.count(anchor) == source.count(before) == 1
    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / "kwt_threebank_core.sv"
    target.write_text(source.replace(before, block + before))
    return target


def generate(parent, target):
    raw = parent.read_text()
    match, = CORE.finditer(raw)
    body = match[1]
    cells = {m[3]: (m[2], connections(m)) for m in INSTANCE.finditer(body)}
    drivers = {pins[pin]: name for name, (ref, pins) in cells.items()
               for pin in split_ports(ref, pins) if pins[pin]}
    uses = Counter(net for ref, pins in cells.values()
                   for pin, net in pins.items() if pin not in split_ports(ref, pins))
    for expression in re.findall(r"(?m)^\s*assign\s+([^;]+);", body):
        uses.update(re.findall(r"\b\w+(?:\[\d+\])?", expression))

    def enable_root(net):
        positive = True
        while net in drivers:
            ref, pins = cells[drivers[net]]
            if not ref.startswith(("BUF", "CLKBUF", "INV", "CLKINV")):
                break
            positive ^= ref.startswith(("INV", "CLKINV"))
            net = pins["I"]
        assert positive, net
        return net

    state = {}
    for name in cells:
        coordinate = STATE.fullmatch(name)
        if coordinate:
            state[tuple(map(int, coordinate.groups()))] = name
    assert set(state) == {(w, b) for w in range(17) for b in range(64)}
    words, checks, removed, replacement, added = [], [], set(), {}, {}
    hold_branches = set()
    for entry in range(17):
        stem = "fifo_entry_%02d" % entry
        clock, gate = stem + "_clk", stem + "_gate"
        roots = set()
        for bit in range(64):
            name = state[(entry, bit)]
            ref, pins = cells[name]
            assert ref == "DQV8_12TR40" and pins["CK"] == "clk", name
            old_d = pins["D"]
            old_cell = drivers[old_d]
            old_ref, old_pins = cells[old_cell]
            assert old_ref == HOLD and old_pins["A1"] == pins["Q"] and uses[old_d] == 1, name
            roots.update(enable_root(old_pins[p]) for p in ("A2", "B1"))
            branch = drivers[old_pins["A2"]]
            if cells[branch][0].startswith(("BUF", "CLKBUF", "INV", "CLKINV")):
                hold_branches.add(branch)
            signal = stem + "_d%02d" % bit
            added[stem + "_nand%02d" % bit] = (
                DATA, dict(A1=old_pins["B1"], A2=old_pins["B2"], ZN=signal))
            replacement[name] = (ref, dict(pins, CK=clock, D=signal))
            removed.add(old_cell)
            checks.append((old_d, pins["Q"], old_pins["A2"], signal))
        enable, = roots
        added[gate] = (ICG, dict(CK="clk", E=enable, TE="1'b0", Q=clock))
        words.append(dict(entry=entry, enable=enable, gate=gate, clock=clock))
        checks[-64:] = [(old_d, q, enable, d) for old_d, q, _, d in checks[-64:]]
    assert len(removed) == BITS and len({word["enable"] for word in words}) == 17
    hold_cells = removed.copy()
    remaining = uses.copy()
    for name in removed:
        ref, pins = cells[name]
        remaining.subtract(net for pin, net in pins.items() if pin not in split_ports(ref, pins))
    for ref, pins in added.values():
        remaining.update(net for pin, net in pins.items() if pin not in split_ports(ref, pins))
    # Follow the disconnected FIFO hold branches upstream to their shared fanout.
    while hold_branches:
        name = hold_branches.pop()
        ref, pins = cells[name]
        output, = split_ports(ref, pins)
        if name in removed or remaining[pins[output]] != 0:
            continue
        removed.add(name)
        remaining[pins["I"]] -= 1
        upstream = drivers.get(pins["I"])
        if upstream and cells[upstream][0].startswith(("BUF", "CLKBUF", "INV", "CLKINV")):
            hold_branches.add(upstream)

    def rewrite(m):
        if m[3] in removed:
            return ""
        if m[3] in replacement:
            ref, pins = replacement[m[3]]
            return render(ref, m[3], pins)
        return m[0]

    edited = INSTANCE.sub(rewrite, body)
    insert = INSTANCE.search(edited).start()
    declarations = "".join("  wire %s;\n" % pins[p] for ref, pins in added.values()
                           for p in sorted(split_ports(ref, pins)))
    edited = edited[:insert] + declarations + edited[insert:]
    edited += "\n".join(render(ref, name, pins) for name, (ref, pins) in added.items()) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw[:match.start(1)] + edited + raw[match.end(1):])
    library, = (ROOT / "build/server/technology").rglob("scc40nll_vhsc40_rvt.v")
    proof(cells, drivers, added, checks, library.read_text(), REPORT / "fifo_next_state.v")
    manifest = dict(variant=NAME, words=words,
                    removed=dict(Counter(cells[name][0] for name in sorted(removed))),
                    orphaned_hold_branches=sorted(removed - hold_cells),
                    added={DATA: BITS, ICG: len(words)}, touched_registers=BITS)
    (REPORT / "eco.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    rtl()
    generate(Path(sys.argv[1]), Path(sys.argv[2]))

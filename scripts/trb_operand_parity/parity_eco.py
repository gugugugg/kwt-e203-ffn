"""Replace the frozen 4x32 operand chain while retaining all consumer nets."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/trb_param_word_gate"), str(ROOT / "scripts/trb_fifo_entry_gate")]
from eco import CORE, INSTANCE, connections, render, split_ports

NAME = "ffn_trb_4x32_operand_parity"
PARENT = "ffn_trb_4x32_fifo_entry_gate"
REPORT = ROOT / "reports/optimization" / NAME
BASE = REPORT.parent / PARENT
TAG = "opt_" + NAME + "_final_ss_ema2"
CHECKPOINT = ROOT / "build/server" / ("complete_soc_sm40_" + TAG)
BITS = 64
TAPS = 16
OLD_FF = re.compile(r"operands_reg_(\d+)__(\d+)_$")
OLD_GATE = re.compile(r"operand_stage_(\d+)__clock_gate$")
SUFFIX = "_12TR40"

RTL_BANKS = """    reg operand_phase;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) operand_phase<=0;
        else operand_phase<=!operand_phase;
    wire [63:0] operand_input=tags[0].side?{input_q[7],input_q[6],input_q[5],input_q[4]}:
        {tags[0].tail?16'b0:input_q[3],input_q[2],input_q[1],input_q[0]};
    reg [63:0] operand_bank [0:15][0:1];
    for (genvar tap=0; tap<16; tap++) begin: operand_taps
        reg last_phase;
        wire advance=tags[2*tap].valid;
        always @(posedge clk) if (advance) last_phase<=operand_phase;
        assign operands[2*tap+1]=operand_bank[tap][last_phase];
        for (genvar bank=0; bank<2; bank++) begin: phases
            wire tap_clk;
            kwt_ffn_clock_gate gate(.clk(clk),.enable(advance&&operand_phase==1'(bank)),
                .test_enable(1'b0),.gated_clk(tap_clk));
            if (tap==0)
                always @(posedge tap_clk) operand_bank[tap][bank]<=operand_input;
            else
                always @(posedge tap_clk) operand_bank[tap][bank]<=operand_bank[tap-1][bank];
        end
    end
"""


def rtl():
    source = (BASE / "kwt_threebank_core.sv").read_text()
    old_decl = "    reg [63:0] operands [1:31];"
    assert source.count(old_decl) == 1
    source = source.replace(old_decl, "    wire [63:0] operands [1:31];")
    start = source.index("    for(genvar index=1;index<=31;index=index+1) begin: operand_stage")
    end = source.index("\n    wire load_input", start)
    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / "kwt_threebank_core.sv"
    target.write_text(source[:start] + RTL_BANKS + source[end:])
    return target


def generate(parent, target):
    raw = parent.read_text()
    match, = CORE.finditer(raw)
    body = match[1]
    cells = {m[3]: (m[2], connections(m)) for m in INSTANCE.finditer(body)}
    states, gates = {}, {}
    uses = defaultdict(list)
    for name, (ref, pins) in cells.items():
        state = OLD_FF.fullmatch(name)
        gate = OLD_GATE.fullmatch(name)
        if state:
            states[tuple(map(int, state.groups()))] = name
        if gate:
            gates[int(gate[1])] = name
        outputs = split_ports(ref, pins) | ({"gated_clk"} if gate else set())
        for pin, signal in pins.items():
            if pin not in outputs:
                uses[signal].append((name, pin))
    assert len(states) == 31 * BITS and set(gates) == set(range(1, 32))

    for stage, gate in sorted(gates.items()):
        _, ports = cells[gate]
        expected = {(states[stage, bit], "CK") for bit in range(BITS)}
        assert set(uses[ports["gated_clk"]]) == expected
        if stage % 2 == 0:
            for bit in range(BITS):
                old_q = cells[states[stage, bit]][1]["Q"]
                assert uses[old_q] == [(states[stage + 1, bit], "D")]
    old_ff = "DQV8" + SUFFIX
    assert all(cells[name][0] == old_ff for name in states.values())
    assert "operand_parity_phase" not in body
    removed = {cells[name][0] for name in gates.values()}
    assert all(ref.startswith("kwt_ffn_clock_gate") for ref in removed)
    additions, updated, wires, taps = {}, {}, [], []

    def new(kind, name, output, **pins):
        assert name not in cells and name not in additions
        additions[name] = (kind + SUFFIX, pins)
        if output is not None:
            wires.append(pins[output])

    phase = "operand_parity_phase"
    phase_n = "operand_parity_phase_n"
    reset = cells["phase_reg"][1]["RDN"]
    new("CLKINV0", "operand_parity_phase_inv", "ZN", I=phase, ZN=phase_n)
    new("DRNQV6", "operand_parity_phase_ff", "Q", CK="clk", RDN=reset, D=phase_n, Q=phase)
    previous = None
    for tap in range(TAPS):
        stem = "operand_parity_t%02d" % tap
        odd = 2 * tap + 1
        advance = cells[gates[odd]][1]["enable"]
        select, select_d = stem + "_select", stem + "_select_d"
        new("MUX2V0", stem + "_sel_mux", "Z", I0=select, I1=phase, S=advance, Z=select_d)
        new("DQV8", stem + "_sel_ff", "Q", CK="clk", D=select_d, Q=select)
        clocks, enables, out, banks = [], [], [], [[], []]
        for bank, when in enumerate((phase_n, phase)):
            enable, clock = stem + "_en%d" % bank, stem + "_clk%d" % bank
            new("AND2V0", stem + "_enable%d" % bank, "Z", A1=advance, A2=when, Z=enable)
            new("CLKLANAQV1", stem + "_gate%d" % bank, "Q", CK="clk", E=enable, TE="1'b0", Q=clock)
            clocks.append(clock)
            enables.append(enable)
        for bit in range(BITS):
            old_odd = states[odd, bit]
            odd_ports = cells[old_odd][1]
            old_q = odd_ports["Q"]
            out.append(old_q)
            for bank in range(2):
                q = stem + "_b%d_q%02d" % (bank, bit)
                d = odd_ports["D"] if previous is None else previous[bank][bit]
                banks[bank].append(q)
                ports = dict(CK=clocks[bank], D=d, Q=q)
                if tap == 0 and bank == 1:
                    new("DQV8", stem + "_bank1_ff%02d" % bit, "Q", **ports)
                else:
                    name = old_odd if bank == 0 else states[2 * tap, bit]
                    updated[name] = (old_ff, ports)
                    wires.append(q)
            external_fanout = sum(not OLD_FF.fullmatch(name) for name, _ in uses[old_q])
            drive = "MUX2V8" if external_fanout >= 16 else "MUX2V2"
            new(drive, stem + "_tap_mux%02d" % bit, None, I0=banks[0][-1], I1=banks[1][-1],
                S=select, Z=old_q)
        previous = banks
        taps.append(dict(index=tap, advance=advance, clocks=clocks, enables=enables, outputs=out))
    assert len(updated) == 1984

    def rewrite(instance):
        name = instance[3]
        if OLD_GATE.fullmatch(name):
            return ""
        if name in updated:
            ref, pins = updated[name]
            return render(ref, name, pins)
        return instance[0]

    edited = INSTANCE.sub(rewrite, body)
    insert = INSTANCE.search(edited).start()
    declarations = "".join("  wire %s;\n" % wire for wire in wires)
    edited = edited[:insert] + declarations + edited[insert:]
    edited += "\n".join(render(ref, name, pins) for name, (ref, pins) in additions.items()) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw[:match.start(1)] + edited + raw[match.end(1):])
    # All removed wrappers contain one CLKLANAQV1 and no other area cells.
    for ref in removed:
        wrapper = re.search(r"(?ms)^module\s+" + re.escape(ref) + r"\b.*?^endmodule", raw)[0]
        assert [m[2] for m in INSTANCE.finditer(wrapper) if m[2] != "module"] == ["CLKLANAQV1" + SUFFIX]
    manifest = dict(variant=NAME, taps=taps, phase=phase,
                    removed={"CLKLANAQV1" + SUFFIX: 31},
                    added=dict(Counter(ref for ref, _ in additions.values())),
                    rewired_data_registers=len(updated))
    (REPORT / "eco.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    rtl()
    generate(Path(sys.argv[1]), Path(sys.argv[2]))

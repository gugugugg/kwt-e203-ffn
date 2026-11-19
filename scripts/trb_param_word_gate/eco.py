"""Factor the per-bit holds out of the frozen parameter register bank."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


NAME = "ffn_trb_4x32_param_word_gate"
SUFFIX = "_12TR40"
CORE = re.compile(r"(?ms)^module kwt_threebank_core\b(.*?)^endmodule")
INSTANCE = re.compile(r"(?ms)^([ \t]*)(\w+)\s+(\\\S+|[\w$]+)\s*\((.*?)\);")
PIN = re.compile(r"\.(\w+)\s*\(\s*([^()]*)\)")
STATE = re.compile(r"(bias|shift)_reg_([01])__(\d+)__(\d+)_$")
OUTPUTS = {"Q", "QN", "Z", "ZN", "CO", "S", "Y"}


def connections(match):
    return {pin: net.strip() for pin, net in PIN.findall(match[4])}


def render(ref, name, pins):
    return "  %s %s (%s);" % (ref, name, ", ".join(
        ".%s(%s%s)" % (pin, net, " " if net.startswith("\\") else "")
        for pin, net in pins.items()
    ))


def factor(q, output, cells, driver, stem):
    top = driver[output]
    ref, pins = cells[top]
    made = {}
    obsolete = {top}

    def instance(kind, name, **ports):
        made[name] = (kind + SUFFIX, ports)

    def inverted(net):
        name = driver.get(net)
        if name and cells[name][0].startswith(("CLKINV", "INV")) and cells[name][1]["I"] == q:
            obsolete.add(name)
            return True
        return False

    data = stem + "_d"
    inv_hold = False
    if ref.startswith("OAI222"):
        feedback, = (letter for letter in "ABC" if any(
            inverted(pins[letter + i]) for i in ("1", "2")))
        hold, = (pins[feedback + i] for i in ("1", "2") if not inverted(pins[feedback + i]))
        inv_hold = True
        keep = [pins[letter + i] for letter in "ABC" if letter != feedback for i in ("1", "2")]
        instance("OAI22V0", stem + "_data", A1=keep[0], A2=keep[1], B1=keep[2], B2=keep[3], ZN=data)
    elif ref.startswith("AOI22BB"):
        assert pins["A1"] == q
        hold = pins["A2"]
        inv_hold = True
        instance("NAND2CV0", stem + "_data", A1=pins["B1"], A2=pins["B2"], ZN=data)
    elif ref.startswith("OAI21") and any(inverted(pins[i]) for i in ("A1", "A2")):
        hold, = (pins[i] for i in ("A1", "A2") if not inverted(pins[i]))
        inv_hold = True
        instance("CLKINV0", stem + "_data", I=pins["B"], ZN=data)
    else:
        assert ref.startswith(("OAI21", "OAI211")), (ref, stem)
        branch, = (pin for pin in ("B", "C") if pin in pins and
                   q in cells[driver[pins[pin]]][1].values())
        child = driver[pins[branch]]
        subref, subpins = cells[child]
        obsolete.add(child)
        if subref.startswith("NAND2C"):
            hold, = (subpins[i] for i in ("A1", "A2") if subpins[i] != q)
            if ref.startswith("OAI211"):
                other = "C" if branch == "B" else "B"
                instance("OAI21V0", stem + "_data", A1=pins["A1"], A2=pins["A2"],
                         B=pins[other], ZN=data)
            else:
                instance("NOR2CV0", stem + "_data", A1=pins["A1"], A2=pins["A2"], ZN=data)
        else:
            assert subref.startswith("AOI22V0") and ref.startswith("OAI21V0"), (subref, stem)
            hit, = (pin for pin in ("A1", "A2", "B1", "B2") if subpins[pin] == q)
            hold = subpins[hit[0] + ("2" if hit[1] == "1" else "1")]
            other = "B" if hit[0] == "A" else "A"
            term = stem + "_term"
            instance("NAND2CV0", stem + "_side", A1=subpins[other + "1"],
                     A2=subpins[other + "2"], ZN=term)
            instance("OAI21V0", stem + "_data", A1=pins["A1"], A2=pins["A2"], B=term, ZN=data)
    return (hold, inv_hold), data, made, obsolete


def split_ports(ref, pins):
    if ref.startswith("RAMSP"):
        return {"Q"}
    if ref.endswith(SUFFIX):
        return OUTPUTS.intersection(pins)
    return set()


def materialize_rtl(parent, target):
    text = parent.read_text()
    anchor = "    wire [63:0] weight_data0={front[1],front[0]};"
    assert text.count(anchor) == 1
    gates = """    for(genvar page=0;page<2;page=page+1) begin: parameter_pages
        for(genvar word=0;word<40;word=word+1) begin: words
            wire eligible=rst_n&&busy&&!load_input&&load_tile[0]==page[0];
            wire lane0=eligible&&load_count!=0&&load_offset==11'(word);
            wire lane1=eligible&&load_count>1&&({1'b0,load_offset}+12'd1)==12'(word);
            wire [31:0] write_data=lane1?front[1]:front[0];
            wire word_clk;
            kwt_ffn_clock_gate word_gate(.clk(clk),.enable(lane0||lane1),
                .test_enable(1'b0),.gated_clk(word_clk));
            if(word<32) begin: bias_word
                always @(posedge word_clk) bias[page][word]<=write_data;
            end else begin: shift_word
                always @(posedge word_clk)
                    for(integer sub=0;sub<4;sub=sub+1)
                        shift[page][4*(word-32)+sub]<=write_data[8*sub+:8];
            end
        end
    end

"""
    text = text.replace(anchor, gates + anchor)
    start = text.index("                    for(integer lane=0;lane<2;lane=lane+1)\n")
    end = text.index("\n                        end", start) + len("\n                        end")
    old = text[start:end]
    assert "bias[load_tile[0]]" in old and "shift[load_tile[0]]" in old
    target.write_text(text[:start] + text[end:])


def generate(parent, target, report, library):
    raw = parent.read_text()
    match, = CORE.finditer(raw)
    body = match[1]
    rows = {m[3]: m for m in INSTANCE.finditer(body)}
    cells = {name: (m[2], connections(m)) for name, m in rows.items()}
    driver = {pins[pin]: name for name, (ref, pins) in cells.items()
              for pin in split_ports(ref, pins) if pins[pin]}
    groups = defaultdict(list)
    for name, (ref, pins) in cells.items():
        state = STATE.fullmatch(name)
        if state:
            kind, page, col, bit = state.groups()
            word = int(col) if kind == "bias" else 32 + int(col) // 4
            assert ref == "DQV8" + SUFFIX and pins["CK"] == "clk", name
            groups[(int(page), word)].append((name, pins))
    assert len(groups) == 80 and all(len(group) == 32 for group in groups.values())
    new, replaced, dead, checks = {}, {}, set(), []
    words = []
    for (page, word), bits in sorted(groups.items()):
        stem = "param_p%d_w%02d" % (page, word)
        packed = []
        for number, (name, pins) in enumerate(sorted(bits)):
            enable, data, made, obsolete = factor(pins["Q"], pins["D"], cells, driver,
                                                 stem + "_b%02d" % number)
            new.update(made)
            dead.update(obsolete)
            packed.append((name, pins, enable, data))
        enable, negative_hold = Counter(row[2] for row in packed).most_common(1)[0][0]
        active = enable
        if not negative_hold:
            active = stem + "_en"
            new[stem + "_inv"] = ("CLKINV0" + SUFFIX, dict(I=enable, ZN=active))
        clock = stem + "_clk"
        new[stem + "_gate"] = ("CLKLANAQV1" + SUFFIX, dict(CK="clk", E=active, TE="1'b0", Q=clock))
        record = dict(page=page, word=word, enable=active, gate=stem + "_gate", clock=clock, bits=[])
        for name, pins, _, data in packed:
            replaced[name] = (cells[name][0], dict(pins, CK=clock, D=data))
            checks.append((pins["D"], pins["Q"], active, data))
            record["bits"].append(dict(name=name, old_d=pins["D"], d=data, q=pins["Q"]))
        words.append(record)

    # Preserve shared fanout and clean the local combinational cells orphaned by the cut.
    survivors = dict(cells, **replaced)
    survivors.update(new)
    uses = Counter(net for ref, pins in survivors.values()
                   for pin, net in pins.items() if pin not in split_ports(ref, pins))
    for expr in re.findall(r"(?m)^\s*assign\s+([^;]+);", body):
        uses.update(re.findall(r"\b\w+(?:\[\d+\])?", expr))
    public_outputs = set(re.findall(r"\b\w+\b", " ".join(
        re.findall(r"(?m)^\s*output\s+([^;]+);", body))))
    removed = set()
    while True:
        ready = {name for name in dead - removed if all(
            not uses[cells[name][1][pin]] for pin in split_ports(*cells[name]))}
        if not ready:
            break
        removed.update(ready)
        for name in ready:
            ref, pins = cells[name]
            inputs = [net for pin, net in pins.items() if pin not in split_ports(ref, pins)]
            uses.subtract(inputs)
            for net in inputs:
                source = driver.get(net)
                if not source or net.split("[", 1)[0] in public_outputs:
                    continue
                source_ref, source_pins = cells[source]
                if split_ports(source_ref, source_pins) in ({"Z"}, {"ZN"}):
                    dead.add(source)
    edited = INSTANCE.sub(lambda m: "" if m[3] in removed else
                          render(replaced[m[3]][0], m[3], replaced[m[3]][1])
                          if m[3] in replaced else m[0], body)
    new_nets = sorted(pins[pin] for ref, pins in new.values() for pin in split_ports(ref, pins))
    first = INSTANCE.search(edited).start()
    edited = edited[:first] + "".join("  wire %s;\n" % net for net in new_nets) + edited[first:]
    edited += "\n".join(render(ref, name, pins) for name, (ref, pins) in new.items()) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw[:match.start(1)] + edited + raw[match.end(1):])
    report.mkdir(parents=True, exist_ok=True)
    manifest = dict(variant=NAME, words=words, removed=dict(Counter(cells[n][0] for n in removed)),
                    added=dict(Counter(ref for ref, _ in new.values())), touched_registers=len(checks))
    (report / "eco.json").write_text(json.dumps(manifest, indent=2) + "\n")
    proof(cells, driver, new, checks, library, report / "word_next_state.v")
    return manifest


def proof(original, drivers, added, checks, library, path):
    """Prove exact old and new next-state functions from the actual cell cones."""
    cells = dict(original, **added)
    drives = dict(drivers)
    drives.update({pins[pin]: name for name, (ref, pins) in added.items()
                   for pin in split_ports(ref, pins) if not ref.startswith("CLKLANA")})
    leaves, nets, needed = set(), {}, {}

    def wire(net):
        if re.fullmatch(r"1'b[01]", net):
            return net
        if net in nets:
            return nets[net]
        alias = "n%d" % len(nets)
        nets[net] = alias
        ref, pins = cells[drives[net]] if net in drives else ("", {})
        if not ref or not split_ports(ref, pins) or "Q" in pins or "QN" in pins:
            leaves.add(alias)
        else:
            needed[drives[net]] = (ref, {p: wire(n) for p, n in pins.items()})
        return alias

    test = ["(%s == (%s ? %s : %s))" % (wire(old), wire(en), wire(data), wire(q))
            for old, q, en, data in checks]
    models = {}
    for ref, _ in needed.values():
        if ref not in models:
            module = re.search(r"(?ms)^module\s+" + ref + r"\s*\(.*?^endmodule", library)[0]
            models[ref] = module.split("`ifdef functional", 1)[0] + "\nendmodule\n"
    # The vendor UDP's binary rows select in0 for 0 and in1 for 1.
    mux = "module udp_mux2(output out,input in0,in1,sel); assign out=sel?in1:in0; endmodule\n"
    text = mux + "\n".join(models.values()) + "\nmodule next_state (input "
    text += ", ".join(sorted(leaves)) + ", output equivalent);\n"
    text += "\n".join("wire " + n + ";" for n in nets.values() if n not in leaves) + "\n"
    text += "\n".join(render(ref, "check_" + str(i), pins)
                      for i, (ref, pins) in enumerate(needed.values())) + "\n"
    text += "wire [%d:0] checks;\n" % (len(test) - 1)
    text += "\n".join("assign checks[%d] = %s;" % (i, item) for i, item in enumerate(test))
    text += "\nassign equivalent = &checks;\nendmodule\n"
    path.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("library", type=Path)
    args = parser.parse_args()
    print({k: v for k, v in generate(args.parent, args.target, args.report,
                                     args.library.read_text()).items() if k != "words"})

"""Materialize the single 4x32 candidate on the corrected 96-MAC platform."""
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = "ffn_trb_4x32"
PARENT = "ffn_trb_sixteen"
BUILD = ROOT / "build/optimization"
SOC = BUILD / "complete_soc" / NAME
SOURCE = BUILD / "rtl_sources" / NAME / "encoder"
REPORT = ROOT / "reports/optimization/ffn_trb_128mac"
IMAGES = BUILD / "ffn_ar_area/frozen/images"


def read_words(path):
    return [int(word, 16) for word in path.read_text().splitlines()]


def pack(case):
    number = 2 * case + 1
    source = read_words(IMAGES / "case_sources.hex")[number]
    inputs = read_words(IMAGES / ("task_%02d_shared.hex" % number))[:3168]
    parameters = read_words(IMAGES / ("linear_layer_%02d_parameters.hex" % source))
    shifts = read_words(IMAGES / ("linear_layer_%02d_metadata.hex" % source))
    assert len(inputs) == 3168 and len(parameters) == 8704 and len(shifts) == 64
    halves = [(word >> bit) & 65535 for word in inputs for bit in (0, 16)]
    identity = [row*64+k for first in range(0, 96, 8) for k in range(64) for row in range(first, first+8)]
    identity.extend(row*64+k for k in range(64) for row in range(96, 99))
    packed = [halves[identity[i]] | (halves[identity[i+1]] << 16) for i in range(0, 6336, 2)]
    packets = []
    for tile in range(8):
        col = tile * 32
        bias = parameters[8192+2*col:8192+2*(col+32)]
        assert all(bias[i+1] == (0xffffffff if bias[i] >> 31 else 0) for i in range(0, 64, 2))
        # The frozen file is tiled in sixteen columns, with eight words per k.
        # Merge both stripes at each k for the wider physical page.
        weight_offsets = ((2*tile+stripe)*512+k*8 for k in range(64) for stripe in range(2))
        weights = [word for offset in weight_offsets for word in parameters[offset:offset+8]]
        packets.extend(bias[::2] + shifts[col//4:col//4+8] + weights)
    source_words = packed + [0] * (32768 - len(packed)) + packets
    order = list(range(256)) + list(range(32768, 33832)) + list(range(256, 3168)) + list(range(33832, 41280))
    assert len(order) == len(set(order)) == 11680
    return order, [source_words[word] for word in order]


def materialize():
    model = json.loads((REPORT / "model-result.json").read_text())
    assert model["passes_4x32"] and len(model["models"]["4x32"]["cases"]) == 12
    assert json.loads((ROOT / "constraints/ffn_selected.json").read_text())["variant"] == "ffn_sg_reuse"
    parent = BUILD / "complete_soc" / PARENT
    parent_source = BUILD / "rtl_sources" / PARENT / "encoder"
    SOURCE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "core.sv", SOURCE / "kwt_threebank_core.sv")
    for name in ("kwt_ffn_requantize.sv", "kwt_ffn_clock_gate.sv"):
        shutil.copyfile(parent_source / name, SOURCE / name)
    for path in list(parent.iterdir()) + list((parent / "eda").glob("*.tcl")):
        if not path.is_file() or path.suffix not in (".sv", ".v", ".svh", ".f", ".json", ".rcf", ".sh", ".tcl"):
            continue
        if path.name in ("gate_tb.sv", "gate_files.f", "compile_gate.sh", "profile_tb.sv", "sram_probes.svh"):
            continue
        data = path.read_text().replace(PARENT, NAME)
        if path.name == "kwt_shared_dma_icb_sm40.sv":
            assert "(!joined_fire||joined_load_read)" in data
        if path.name == "power.tcl":
            data = data.replace("reports/optimization/" + NAME + "/activity-mapping/",
                                REPORT.relative_to(ROOT).as_posix() + "/activity-mapping/")
        if path.name == "configuration.json":
            config = json.loads(data)
            config.update(parent_variant=PARENT, compute_mac_count=128, requantizers=8)
            data = json.dumps(config, indent=2) + "\n"
        target = SOC / path.relative_to(parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
    inputs = SOC / "packed_inputs"
    inputs.mkdir(exist_ok=True)
    for case in range(12):
        addresses, words = pack(case)
        (inputs / ("task_%02d_payload.hex" % (case+1))).write_text("".join("%08x\n" % word for word in words))
        (inputs / ("task_%02d_addresses.hex" % (case+1))).write_text("".join("%05x\n" % address for address in addresses))


if __name__ == "__main__":
    materialize()

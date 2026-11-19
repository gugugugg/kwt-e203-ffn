"""Recapture only private macro Q activity on the accepted cold-task stimulus."""
from concurrent.futures import ThreadPoolExecutor
import re
import sys

from native import ROOT, NAME, REPORT, OUT, DEST, job, preflight, read, save, settings

EVIDENCE = REPORT / "memory-observed"
REPLAY = EVIDENCE / "replayed"
WORK = OUT / "observed_power"
CORE = ROOT / "build/optimization/rtl_sources" / NAME / "encoder/kwt_threebank_core.sv"
OBSERVATION = """
    reg [383:0] observed_private_q;
    integer observe_bit_bank;
    always @* begin
        for (observe_bit_bank=0;observe_bit_bank<8;observe_bit_bank=observe_bit_bank+1)
            observed_private_q[16*observe_bit_bank+:16]=input_q[observe_bit_bank];
        for (observe_bit_bank=0;observe_bit_bank<16;observe_bit_bank=observe_bit_bank+1)
            observed_private_q[128+16*observe_bit_bank+:16]=weight_q[observe_bit_bank];
    end
"""
BIT_RECORD = re.compile(rb"\(\s*observed_private_q\\?\[(\d+)\\?\]\s+((?:\([^()]+\)\s*)+)\)")
CORE_NET = re.compile(rb"\(INSTANCE\s+core\s+\(NET\b")
DURATION = re.compile(rb"\(DURATION\s+([^\s)]+)")
MARKERS = ("UNIFIED_PUBLIC_TASK_PASS", "THREEBANK_COUNTS")
SCOPE = "soc/u_e203_subsys_main/u_e203_subsys_perips/accelerator/core/"


def prepare_mapping():
    from phase_local import REVIEW
    from sr_area_phase_review import native_index

    native = native_index(REVIEW / "segments.rpt")
    rows = []
    for base, count, stem in ((0, 8, "input_and_result"), (128, 16, "weight_columns")):
        for bank in range(count):
            cell = "{}{}_{}__memory".format(SCOPE, stem, bank)
            for bit in range(16):
                pin = "{}/Q[{}]".format(cell, bit)
                gate, = native["pin", pin]["nets"]
                index = base + 16 * bank + bit
                rows.append(dict(index=index, pin=pin, gate=gate,
                                 rtl="{}observed_private_q[{}]".format(SCOPE, index)))
    assert len({row["gate"] for row in rows}) == 384
    save(EVIDENCE / "memory-observed-q-map.json", rows)


def build():
    REPLAY.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    sim = WORK / "sim"
    if sim.exists():
        return sim
    source = CORE.read_text()
    assert source.count("\nendmodule") == 1
    observed = EVIDENCE / CORE.name
    observed.write_text(source.replace("\nendmodule", OBSERVATION + "\nendmodule", 1))
    files = (OUT / "files.f").read_text()
    needle = CORE.relative_to(ROOT).as_posix()
    assert files.count(needle) == 1
    filelist = EVIDENCE / "files.f"
    filelist.write_text(files.replace(needle, observed.relative_to(ROOT).as_posix()))
    upstream = "build/server/official_2025/e203_hbirdv2-master/rtl/e203"
    include = "+incdir+" + "+".join((OUT.relative_to(ROOT).as_posix(), "rtl/public_encoder",
        upstream + "/core", upstream + "/perips", upstream + "/perips/apb_i2c"))
    job(["vcs", "-full64", "-sverilog", "+delay_mode_distributed", "+notimingcheck",
         "-timescale=1ns/1ps", "+define+ARM_UD_MODEL+DISABLE_SV_ASSERTION=1",
         "-debug_access+all", include, "-top", "complete_soc_tb", "-f", filelist,
         "-Mdir=" + str(WORK / "csrc"), "-o", sim], EVIDENCE / "compile.log")
    return sim


def capture(sim, case):
    label = "%02d" % case
    measured = EVIDENCE / ("case_" + label + ".json")
    if measured.is_file():
        return read(measured)
    out = REPLAY / ("run_" + label + ".log")
    trace = REPLAY / ("activity_" + label + ".saif")
    if not trace.is_file():
        job([sim, "+FIRST_TASK=" + str(case), "+TASKS=1",
             "+RESULT_DIR=" + str(REPLAY.relative_to(ROOT)),
             "+SAIF=" + str((REPLAY / "activity").relative_to(ROOT))], out)
    original_log = (DEST / ("run_" + label + ".log")).read_text()
    observed_log = out.read_text()
    for marker in MARKERS:
        pattern = r"(?m)^" + marker + r" .+$"
        assert re.findall(pattern, original_log) == re.findall(pattern, observed_log)
    assert "UNIFIED_PUBLIC_ALL_PASS" in observed_log
    original = (DEST / trace.name).read_bytes()
    observed = trace.read_bytes()
    duration = DURATION.search(original).group(1)
    assert DURATION.search(observed).group(1) == duration
    core, = CORE_NET.finditer(original)
    records = {int(m[1]): m for m in BIT_RECORD.finditer(observed)}
    assert set(records) == set(range(384)), ("SAIF Q coverage", len(records))
    values = {}
    for index, record in sorted(records.items()):
        values[index] = {key.decode(): float(value) for key, value in
                         re.findall(rb"\(([A-Z0-9]+)\s+([0-9.]+)\)", record[2])}
    assert all("T0" in v and "T1" in v and "TX" in v and "TC" in v for v in values.values())
    insertion = b"\n" + b"\n".join(records[i][0] for i in range(384)) + b"\n"
    joined = original[:core.end()] + insertion + original[core.end():]
    merged = EVIDENCE / trace.name
    merged.write_bytes(joined)
    trace.unlink()
    result = dict(case=case, duration_ns=float(duration), observed_bits=384, values=values,
                  replay_acceptance_equal=True, merged_saif=merged.relative_to(ROOT).as_posix())
    save(measured, result)
    print("THREEBANK_OBSERVED_Q", case, len(values), flush=True)
    return result


def main():
    if sys.argv[1] == "map":
        prepare_mapping()
        return
    preflight()
    sim = build()
    cases = [1] if sys.argv[1] == "first" else list(range(1, 24, 2))
    capture(sim, cases[0])
    with ThreadPoolExecutor(max_workers=settings()["cpu_case_workers"]) as pool:
        list(pool.map(lambda case: capture(sim, case), cases[1:]))


if __name__ == "__main__":
    main()


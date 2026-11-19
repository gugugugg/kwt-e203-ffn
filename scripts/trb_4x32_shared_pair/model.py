"""Compare the FIFO release transport with an arbitrated two-word result write."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/optimization/ffn_trb_4x32_shared_pair"
FIFO_REPORT = ROOT / "reports/optimization/ffn_trb_4x32_fifo_entry_gate"
NATIVE = FIFO_REPORT / "received/full/native-evidence" / FIFO_REPORT.relative_to(ROOT)
SPEC = importlib.util.spec_from_file_location("wide_reference", ROOT / "scripts/trb_128mac/model.py")
wide = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wide)
from supply_study import mapped_word


CLOCK = 150_000_000
READ_WORDS = 11680
WRITE_WORDS = wide.RESULT_WORDS
RESULT_BASE = wide.base.RESULT_BASE
TARGET_CYCLES = CLOCK // 10_000


def shared_word(address):
    if RESULT_BASE <= address < RESULT_BASE + 0x4000:
        return (address & ~0x1001) | ((address & 1) << 12) | ((address >> 12) & 1)
    return mapped_word(address)


class SharedPairTask(wide.WideTask):
    def __init__(self, case, startup):
        super().__init__(case, 4, startup)
        self.drain = False
        self.slot_pressure = False
        self.physical_results = {}
        self.pair_trace = []
        self.capture_pair_trace = case == 0

    def result_slots_under_pressure(self):
        tile = self.oldest
        if tile == len(self.layout.widths):
            return False
        page = self.pages[tile % 2]
        if page is not None and page.next_unit == self.pairs + 1:
            tile += 1
        if tile == len(self.layout.widths):
            return False
        page = self.pages[tile % 2]
        required = 1 if page is not None and page.next_unit == self.pairs else 2
        return len(self.slots[0]) + required > 8

    def source_ready(self):
        return self.source_candidate() is not None and self.read_credit() < 8

    def issue(self, ports):
        # A reservation made by issue() is visible to arbitration on the next edge.
        self.slot_pressure = self.result_slots_under_pressure()
        super().issue(ports)

    def write_pair(self, occupied):
        low, high = self.out_held[0], self.out_held[1]
        slot, index, _ = low
        assert high[0] is slot and index % 4 == 0 and high[1] == index + 2
        logical = RESULT_BASE + index // 2
        physical = shared_word(logical), shared_word(logical + 1)
        banks = {word >> 12 for word in physical}
        assert banks in ({4, 5}, {6, 7}) and not banks & occupied
        occupied.update(banks)
        for physical_word in physical:
            packet = self.out_held.popleft()
            assert physical_word not in self.physical_results
            self.physical_results[physical_word] = packet[2]
            self.write_shared(packet)
            self.record("write", RESULT_BASE + packet[1] // 2)
        self.write_ack = self.cycle
        self.stats["pair_commits"] += 1
        if self.capture_pair_trace:
            self.pair_trace.append([self.cycle, logical, *physical])

    def transfer(self, ports):
        occupied = set()
        cpu_busy = self.cycle in self.cpu_reserved
        setup = self.cpu_setup.get(self.cycle)
        if setup:
            address = (setup["accept_addr"] - wide.base.baseline.t.BASE) // 4
            occupied.add(shared_word(address) >> 12)

        # New command eligibility uses pre-edge input commits and queue entries.
        old_reads = self.returning
        old_write = self.write_ack
        assert not (old_reads and old_write is not None)
        old_direction = "read" if old_reads else "write" if old_write is not None else None
        pair_ready = len(self.out_held) >= 2
        read_ready = self.source_ready() if not cpu_busy else False
        credit = len(self.out_held) + len(self.out_pending)
        pressure = credit >= 32 or self.slot_pressure
        self.drain = pair_ready and (self.drain or pressure or not read_ready)
        request = "write" if self.drain else "read" if read_ready else None
        if cpu_busy:
            request = None
            self.stats["cpu_reserved_cycles"] += 1
        if request and old_direction and request != old_direction:
            self.stats[old_direction + "_to_" + request + "_bubbles"] += 1
            request = None

        # Reads reserve the existing credits until their previous responses
        # move to the load queue. A pair ACK retires two already committed words.
        grants = self.accept_reads(occupied) if request == "read" else []
        self.write_ack = None
        if old_write is not None:
            assert old_write == self.cycle - 1
            self.stats["pair_acks"] += 1
            self.stats["write_ack"] += 2
            self.record("ack")
            self.record("ack")
            if self.stats["write_ack"] == WRITE_WORDS:
                self.marks["final_ack"] = self.cycle
        if request == "write":
            self.write_pair(occupied)
            self.stats["consecutive_pair_writes"] += old_write is not None

        # Retain loader overlap on DMA reads. The original controller does
        # not grant loader streaming on an accepted DMA write.
        host_count = self.accept_loader(occupied) if not cpu_busy and request != "write" else 0
        if (cpu_busy or request == "write") and self.host_index < len(self.host_order):
            self.stats["host_wait_owner"] += 1
        self.stats["dual_source_edges"] += len(grants) == 2
        self.stats["dual_loader_edges"] += host_count == 2
        self.stats["two_read_two_write_edges"] += len(grants) == host_count == 2
        self.stats["source_read_edges"] += bool(grants)
        self.stats["host_source_overlap_edges"] += bool(grants and host_count)
        for packet in old_reads:
            self.incoming.append(packet)
            self.record("source_return")
        self.returning = grants

        self.out_held.extend(self.out_pending)
        self.out_pending = []
        self.prefetch_output(ports)
        self.read_peak = max(self.read_peak, self.read_credit())
        self.output_credit_peak = max(self.output_credit_peak, len(self.out_held) + len(self.out_pending))
        assert self.read_peak <= 8 and self.output_credit_peak <= self.output_credit_limit
        self.stats["shared_bank_accesses_" + str(len(occupied))] += 1

    def run(self):
        row = super().run()
        if row["complete"]:
            assert self.stats["pair_commits"] == self.stats["pair_acks"] == WRITE_WORDS // 2
            assert len(self.physical_results) == WRITE_WORDS
            for offset, logical_value in enumerate(range(RESULT_BASE, RESULT_BASE + WRITE_WORDS)):
                data = self.physical_results[shared_word(logical_value)]
                assert wide.base.halves(data) == tuple(self.golden[2 * offset:2 * offset + 2])
        return row


def native_case(case):
    case_id = 2 * case + 1
    log = (NATIVE / "gate-activity" / ("run_%02d.log" % case_id)).read_text(encoding="utf-8")
    receipt = {}
    for marker in ("THREEBANK_COUNTS", "UNIFIED_PUBLIC_TASK_PASS"):
        line, = re.findall(r"(?m)^" + marker + r" (.*)$", log)
        fields = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
        assert fields["case"] == case_id
        receipt.update(fields)
    return receipt


def run_case(args):
    shared, case, startup = args
    task = SharedPairTask(case, startup) if shared else wide.WideTask(case, 4, startup)
    row = task.run()
    row["native_case_id"] = 2 * case + 1
    if not shared:
        native = native_case(case)
        assert row["complete"] and row["cold_cycles"] == native["cycles"]
        assert row["final_physical_commit"] == native["last_commit"]
        assert row["final_ack"] == native["last_ack"]
        assert native["reads"] == native["host_payload"] == READ_WORDS
        assert native["writes"] == native["acks"] == WRITE_WORDS and native["outputs"] == 25344
        row["native_calibration"] = native
    return row, task.pair_trace if shared and case == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", action="store_true")
    args = parser.parse_args()
    window = range(RESULT_BASE, RESULT_BASE + 0x4000)
    assert set(map(shared_word, window)) == set(window)
    assert all(shared_word(shared_word(word)) == word for word in window)
    startup, _ = wide.calibrated_startup()
    cases = range(1 if args.first else 12)
    results = {}
    trace = None
    with ProcessPoolExecutor(max_workers=4) as pool:
        for shared, name in ((False, "fifo_control"), (True, "shared_pair")):
            rows = []
            for row, pair_trace in pool.map(run_case, ((shared, case, startup) for case in cases)):
                rows.append(row)
                if pair_trace is not None:
                    trace = pair_trace
            complete = all(row["complete"] for row in rows)
            total = sum(row["cold_cycles"] for row in rows) if complete else None
            results[name] = dict(complete=complete, cycles_total=total,
                                 throughput=len(rows) * CLOCK / total if total else None,
                                 cycles_above_10k_budget=total - len(rows) * TARGET_CYCLES if total else None,
                                 rows=rows)
            print(name, total, results[name]["throughput"],
                  [(row["first_issue"], row["final_physical_commit"], row["final_ack"], row["slot_peak"])
                   for row in rows], flush=True)
    if not args.first:
        REPORT.mkdir(parents=True, exist_ok=True)
        (REPORT / "model-result.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        if results["shared_pair"]["complete"]:
            assert len(trace) == WRITE_WORDS // 2
        (REPORT / "case01-pair-commits.json").write_text(json.dumps({
            "columns": ["cycle", "logical_word", "physical_low_word", "physical_high_word"],
            "rows": trace,
        }, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

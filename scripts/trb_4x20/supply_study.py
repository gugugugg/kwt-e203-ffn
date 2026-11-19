"""Screen the fixed four 4脳20 transport and launch configurations."""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

from causal import ROOT, Task, base, observation

REPORT = ROOT / "reports/optimization/ffn_trb_4x20_7k"
MODES = ("M0", "R", "D", "D+R")
TARGET_CYCLES = 257142
INPUT_WORDS = 3168
PARAMETER_WORDS = 8512
PAYLOAD_WORDS = INPUT_WORDS + PARAMETER_WORDS


def mapped_word(address):
    """Exchange the two stripe bits with the two bank bits in each full region."""
    if address >> 14 in (0, 2):
        return ((address & ~0x3003)
                | ((address & 3) << 12)
                | ((address >> 12) & 3))
    return address


def mapped_bank(address):
    return mapped_word(address) >> 12


class SupplyTask(Task):
    def __init__(self, case, mode, startup):
        super().__init__(case, 20, startup)
        self.dual = mode in ("D", "D+R")
        self.reorder = mode in ("R", "D+R")
        self.returning = []
        self.output_credit_limit = 2
        self.first_unit_done = None
        if self.reorder:
            # The original first packet occupies the first 665 source positions.
            # Move exactly one regular input unit before it.
            packet = self.layout.sizes[0]
            prefix = self.order[packet:packet + 256]
            assert prefix == list(range(256))
            self.order = prefix + self.order[:packet] + self.order[packet + 256:]
        if self.dual:
            self.repack_inputs()
        self.host_order = [(0, self.source[0])] + startup["controls"]
        self.host_order.extend((address, self.source[address]) for address in self.order if address)

    def repack_inputs(self):
        values = {}
        for address in range(INPUT_WORDS):
            identities = self.identities[2 * address:2 * address + 2]
            values.update(zip(identities, base.halves(self.source[address])))
        ordered = [(row, k) for pair in range(12) for k in range(64)
                   for row in range(8 * pair, 8 * pair + 8)]
        ordered.extend(self.identities[6144:])
        assert len(ordered) == 2 * INPUT_WORDS and len(set(ordered)) == len(values)
        for address in range(INPUT_WORDS):
            first, second = ordered[2 * address:2 * address + 2]
            self.source[address] = base.packed(values[first], values[second])
        self.identities = ordered

    def unit_readiness(self, tile, pair):
        if self.reorder and tile < 2 and pair < 12:
            width = self.layout.widths[tile]
            return width + width // 4 + width // 2, 256 * pair + 4
        return super().unit_readiness(tile, pair)

    def input_ready_for_issue(self, tile, pair, k):
        if self.reorder and tile < 2 and pair < 12:
            return self.input_written >= 256 * pair + 4 * (k + 1)
        return True

    def issue(self, ports):
        previous = len(self.events["issue"])
        super().issue(ports)
        if len(self.events["issue"]) != previous:
            tile, pair, index = self.identities_by_event["issue"][-1]
            if (tile, pair, index) == (0, 0, 127):
                self.first_unit_done = self.cycle

    def load_kind(self, address):
        if address < INPUT_WORDS:
            return "input"
        tile, offset = self.layout.param(address)
        width = self.layout.widths[tile]
        return "header" if offset < width + width // 4 else "weight"

    def load_private(self, ports, weight_ports):
        if not self.dual or not self.incoming:
            return super().load_private(ports, weight_ports)
        address, _ = self.incoming[0]
        kind = self.load_kind(address)
        budget = {"header": 2, "weight": 4, "input": 1}[kind]
        if kind == "input" and address < 3072 and address % 2 == 0:
            budget = 2
        quartets_before = self.stats["weight_write64"]
        loaded_before = len(self.events["load"])
        for _ in range(budget):
            if not self.incoming or self.load_kind(self.incoming[0][0]) != kind:
                break
            if self.stats["weight_write64"] - quartets_before == 2:
                break
            queued = len(self.incoming)
            # This reuses the scalar arithmetic/address logic. Its port sets
            # include all earlier grants from the current edge.
            super().load_private(ports, weight_ports)
            if len(self.incoming) == queued:
                break
        if len(self.events["load"]) - loaded_before >= 2:
            self.stats[f"private_{kind}_multiword_edges"] += 1
        if self.stats["weight_write64"] - quartets_before == 2:
            self.stats["private_dual_quartet_edges"] += 1

    def read_credit(self):
        return len(self.incoming) + len(self.returning) + int(self.weight_pack is not None)

    def source_candidate(self):
        if self.cycle <= self.kickoff or self.read_index == PAYLOAD_WORDS:
            return None
        address = self.order[self.read_index]
        if address not in self.shared:
            self.stats["source_wait_uncommitted"] += 1
            return None
        if address >= base.PARAMETER_BASE:
            tile, offset = self.layout.param(address)
            page = self.pages[tile % 2]
            if tile > self.oldest + 1 or (page is not None and page.tile != tile):
                self.stats["dma_wait_page_release"] += 1
                return None
            assert page is not None or offset == 0
        return address

    def accept_reads(self, occupied):
        old_credit = self.read_credit()
        grants = []
        if old_credit == 8:
            self.stats["source_full_credit_edges"] += 1
        for _ in range(min(2, 8 - old_credit)):
            address = self.source_candidate()
            if address is None:
                break
            bank = mapped_bank(address)
            if bank in occupied:
                self.stats["source_bank_conflict_edges"] += 1
                break
            occupied.add(bank)
            if address >= base.PARAMETER_BASE:
                tile, offset = self.layout.param(address)
                if offset == 0:
                    assert self.pages[tile % 2] is None
                    page = base.Page(tile)
                    page.bias = [None] * self.layout.stride
                    page.shift = [None] * self.layout.stride
                    self.pages[tile % 2] = page
            self.read_index += 1
            grants.append((address, self.shared[address]))
            self.record("source_fire", 0xa0000000 + 4 * address)
        return grants

    def accept_loader(self, occupied):
        accepted = 0
        for lane in range(2):
            if self.host_index >= len(self.host_order) or self.cycle < self.host_start:
                break
            address, value = self.host_order[self.host_index]
            payload = address in self.source
            # The first word and the ten control/guard handshakes use the
            # frozen startup path. No second lane may skip a blocked head.
            if lane and (self.host_index <= 11 or not payload):
                break
            bank = mapped_bank(address)
            if bank in occupied:
                self.stats["host_wait_same_bank"] += 1
                break
            occupied.add(bank)
            assert address not in self.out_memory
            if payload:
                assert address not in self.shared
                self.stats["host_payload_commits"] += 1
                self.marks.setdefault("first_host_physical_commit", self.cycle)
            else:
                self.stats["host_setup_commits"] += 1
            self.shared[address] = value
            self.host_index += 1
            self.record("host", address)
            accepted += 1
            if not payload:
                break
        return accepted

    def pending_result_count(self):
        return int(self.out_pending is not None)

    def transfer(self, ports):
        if not self.dual:
            return super().transfer(ports)
        occupied = set()
        cpu_busy = self.cycle in self.cpu_reserved
        setup = self.cpu_setup.get(self.cycle)
        if setup:
            address = (setup["accept_addr"] - base.baseline.t.BASE) // 4
            occupied.add(mapped_bank(address))
        # Requests observe only pre-edge loader commits. A prior read's
        # return does not consume a bank port on this edge.
        grants = self.accept_reads(occupied) if not cpu_busy else []
        host_count = self.accept_loader(occupied) if not cpu_busy else 0
        if cpu_busy and self.host_index < len(self.host_order):
            self.stats["host_wait_owner"] += 1
        self.stats["dual_source_edges"] += len(grants) == 2
        self.stats["dual_loader_edges"] += host_count == 2
        self.stats["two_read_two_write_edges"] += len(grants) == host_count == 2
        for address, word in self.returning:
            self.incoming.append((address, word))
            self.record("source_return")
        self.returning = grants
        self.transfer_results(ports, occupied, bool(grants and host_count))
        self.read_peak = max(self.read_peak, self.read_credit())
        self.output_credit_peak = max(self.output_credit_peak,
                                      len(self.out_held) + self.pending_result_count())
        assert self.read_peak <= 8 and self.output_credit_peak <= self.output_credit_limit
        self.stats[f"shared_bank_accesses_{len(occupied)}"] += 1

    def summary(self, complete):
        row = super().summary(complete)
        row["first_issue"] = self.events["issue"][0] if self.events["issue"] else None
        row["first_unit_last_issue"] = self.first_unit_done
        row["first_page_release"] = self.events["page_release"][0] if self.events["page_release"] else None
        row["last_issue"] = self.events["issue"][-1] if self.events["issue"] else None
        row["input_fully_committed"] = self.input_written
        row["event_counts"] = {name:len(events) for name, events in self.events.items()}
        return row


def run_case(args):
    mode, case, startup = args
    task = SupplyTask(case, mode, startup)
    row = task.run()
    if row["complete"]:
        assert row["event_counts"]["host"] == PAYLOAD_WORDS + 10
        assert row["event_counts"]["source_return"] == PAYLOAD_WORDS
        assert row["event_counts"]["ack"] == 12672
        assert row["counters"]["quant_halfwords"] == 25344
    return row


def model_record(rows):
    complete = all(row["complete"] for row in rows)
    total = sum(row["cold_cycles"] for row in rows) if complete else None
    return dict(complete=complete, total_cycles=total,
                throughput=1_800_000_000 / total if total else None,
                passes=total is not None and total <= TARGET_CYCLES, rows=rows)


def main():
    startup, _, _ = observation()
    assert startup["start"] == 162
    # All logical addresses remain distinct, including guard/CPU words.
    assert len({mapped_word(address) for address in range(1 << 17)}) == 1 << 17
    if "--first" in sys.argv:
        modes = [mode for mode in MODES if mode in sys.argv] or MODES
        for mode in modes:
            row = run_case((mode, 0, startup))
            print(mode, json.dumps({key:row[key] for key in (
                "complete", "cold_cycles", "first_issue", "first_unit_last_issue",
                "last_issue", "final_physical_commit", "final_ack", "counters")}), flush=True)
        return
    REPORT.mkdir(parents=True, exist_ok=True)
    results = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for mode in MODES:
            rows = list(pool.map(run_case, ((mode, case, startup) for case in range(12))))
            results[mode] = model_record(rows)
            if mode == "M0":
                assert results[mode]["total_cycles"] == 285300
                anchors = {"first_issue":1086, "last_emit":23748,
                           "final_physical_commit":23774, "final_ack":23775}
                assert all(all(row[key] == value for key,value in anchors.items()) for row in rows)
            print(mode, results[mode]["total_cycles"], results[mode]["throughput"],
                  [row["cold_cycles"] for row in rows], flush=True)
    viable = [mode for mode in MODES if results[mode]["passes"]]
    selected = min(viable, key=lambda mode:(results[mode]["total_cycles"], MODES.index(mode))) if viable else None
    report = dict(start_edge=startup["start"], target_cycles=TARGET_CYCLES,
                  selected=selected, model_results=results)
    (REPORT/"model-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("SCREEN", selected, flush=True)


if __name__ == "__main__":
    main()

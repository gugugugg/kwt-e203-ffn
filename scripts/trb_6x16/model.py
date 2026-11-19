"""Cycle model for six input rows, sixteen columns and independent result SRAM."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "trb_4x20"))
from causal import Layout, Slot, Task, base, observation
from supply_study import SupplyTask, mapped_word

ROOT = HERE.parents[1]
REPORT = ROOT / "reports/optimization/ffn_trb_6x16"
INPUT_WORDS = 3168
RESULT_WORDS = 12672
TILES = 16
UNITS = 9
ISSUES = TILES * (8 * 128 + 64)
TARGET = 257142


def input_location(row, k):
    if row < 96:
        return row % 6, row // 6 * 64 + k
    return 6 + row - 96, k


class ResultSlot(Slot):
    @property
    def rows(self):
        return 3 if self.group == 16 else 6

    @property
    def words(self):
        return self.rows * 8

    def cell(self, row, col):
        return (row + col) % 6, self.index * 16 + col


class SixRowTask(SupplyTask):
    def __init__(self, case, scratch_lanes, startup):
        super().__init__(case, "D", startup)
        self.layout = Layout(16)
        self.source, _, original_ids = self.layout.pack(case)
        original_input = {}
        for address in range(INPUT_WORDS):
            ids = original_ids[2 * address:2 * address + 2]
            original_input.update(zip(ids, base.halves(self.source[address])))
        self.identities = [(row, k) for first in range(0, 96, 12) for k in range(64)
                           for row in range(first, first + 12)]
        self.identities.extend((row, k) for k in range(64) for row in range(96, 99))
        assert len(self.identities) == len(set(self.identities)) == 2 * INPUT_WORDS
        for address in range(INPUT_WORDS):
            first, second = self.identities[2 * address:2 * address + 2]
            self.source[address] = base.packed(original_input[first], original_input[second])
        self.order = list(range(INPUT_WORDS)) + list(range(base.PARAMETER_BASE, base.PARAMETER_BASE + 8512))
        self.host_order = [(0, self.source[0])] + startup["controls"]
        self.host_order.extend((address, self.source[address]) for address in self.order if address)
        self.input_banks = [[None] * 1024 for _ in range(6)] + [[None] * 128 for _ in range(3)]
        self.result_banks = [[None] * 128 for _ in range(6)]
        self.scratch_lanes = scratch_lanes
        self.output_credit_limit = 2 * scratch_lanes
        self.out_pending = []

    def pending_result_count(self):
        return len(self.out_pending)

    def reserve(self, page, pair):
        slots = []
        for group in range(2 * pair, min(2 * pair + 2, 17)):
            index = self.next_slot[0]
            assert all(slot.index != index for slot in self.slots[0])
            slot = ResultSlot(0, index, page.tile, group, self.slot_sequence, self.layout)
            self.slot_sequence += 1
            self.slots[0].append(slot)
            self.next_slot[0] = (index + 1) % 8
            slots.append(slot)
        self.ring_peak[0] = max(self.ring_peak[0], len(self.slots[0]))
        return tuple(slots)

    def start_unit(self):
        if self.cycle <= self.kickoff:
            return "prelude"
        if self.input_written != INPUT_WORDS:
            return "input_prefix"
        if self.oldest == TILES:
            return "pipeline_or_output"
        tile = self.oldest
        old = self.pages[tile % 2]
        if old is not None and old.next_unit == UNITS:
            tile += 1
        if tile == TILES:
            return "pipeline_or_output"
        page = self.pages[tile % 2]
        if page is None or page.next_unit == UNITS or page.written != self.layout.sizes[tile]:
            return "weight_page"
        pair = page.next_unit
        required = 1 if pair == 8 else 2
        if len(self.slots[0]) + required > 8:
            return "result_slots"
        if pair != 8 and self.phase():
            return "pair_phase"
        page.next_unit += 1
        self.unit = base.Unit(page, pair, self.reserve(page, pair))
        self.unit_history.append([self.cycle, page.tile, pair])
        return None

    def issue(self, ports):
        if self.unit is None:
            reason = self.start_unit()
            if reason:
                self.stats["issue_wait_" + reason] += 1
                return
        unit = self.unit
        paired = unit.pair != 8
        index = unit.index
        slot = unit.slots[index % 2] if paired else unit.slots[0]
        k = index // 2 if paired else index
        values = []
        for row in range(6 * slot.group, 6 * slot.group + slot.rows):
            bank, address = input_location(row, k)
            stored, value = self.input_banks[bank][address]
            assert stored == row
            values.append(value)
        self.tokens[self.cycle % 64] = base.Token(slot, k, tuple(values), not paired or index % 2 == 0)
        self.max_last_issue = self.cycle
        self.issue_count += 1
        self.stats["input_macro_reads"] += len(values)
        unit.index += 1
        if unit.index == (128 if paired else 64):
            self.unit = None
        self.record("issue", slot.tile, unit.pair, index)

    def finish_output_column(self, ports):
        event = self.quant.pop(self.cycle, None)
        if event is None:
            return
        slot, col, values = event
        assert col == slot.columns and len(values) == slot.rows
        for row, value in enumerate(values):
            bank, address = slot.cell(row, col)
            assert bank not in ports and self.result_banks[bank][address] is None
            self.result_banks[bank][address] = slot.sequence, value
            ports.add(bank)
        slot.columns += 1
        self.stats["quant_halfwords"] += len(values)
        self.marks["last_emit"] = self.cycle
        if slot.columns == 16:
            slot.completed_edge = self.cycle
            self.pages[slot.tile % 2].emitted += 1
        self.record("quant", col, slot.side)

    def load_private(self, ports, weight_ports):
        if not self.incoming or self.incoming[0][0] >= INPUT_WORDS:
            return super().load_private(set(), weight_ports)
        assert self.weight_pack is None and self.issue_count == 0
        first = self.incoming[0][0]
        occupied = set()
        for _ in range(2 if first < 3072 else 1):
            if not self.incoming or self.incoming[0][0] >= (3072 if first < 3072 else INPUT_WORDS):
                break
            address, data = self.incoming[0]
            assert address == self.input_written
            rows = self.identities[2 * address:2 * address + 2]
            cells = [input_location(row, k) for row, k in rows]
            banks = {bank for bank, _ in cells}
            assert len(banks) == 2
            if banks & occupied:
                break
            for (row, _), (bank, index), value in zip(rows, cells, base.halves(data)):
                assert self.input_banks[bank][index] is None
                self.input_banks[bank][index] = row, value
            occupied.update(banks)
            self.incoming.popleft()
            self.input_written += 1
            self.record("load")
        self.stats["private_input_multiword_edges"] += len(occupied) == 4
        if self.input_written == INPUT_WORDS:
            self.marks["input_commit_edge"] = self.cycle

    def prefetch_output(self, ports):
        slot = next((slot for slot in self.slots[0] if slot.reads < slot.words), None)
        if slot is None or slot.completed_edge is None or slot.completed_edge == self.cycle:
            return
        available = self.output_credit_limit - len(self.out_held)
        if not available:
            self.stats["scratch_credit_blocked_edges"] += 1
            return
        for _ in range(min(self.scratch_lanes, available, slot.words - slot.reads)):
            row, pair = divmod(slot.reads, 8)
            cells = [slot.cell(row, 2 * pair + half) for half in range(2)]
            if any(bank in ports for bank, _ in cells):
                self.stats["scratch_bank_conflict_edges"] += 1
                self.stats["scratch_second_lane_conflict_edges"] += bool(self.out_pending)
                break
            values = []
            for bank, address in cells:
                owner, value = self.result_banks[bank][address]
                assert owner == slot.sequence
                values.append(value)
                ports.add(bank)
            index = (6 * slot.group + row) * 256 + 16 * slot.tile + 2 * pair
            assert tuple(values) == tuple(self.golden[index:index + 2]), (self.case, self.cycle, index)
            self.out_pending.append((slot, index, base.packed(*values)))
            slot.reads += 1
            self.stats["result_macro_reads"] += 2
            self.record("scratch", slot.side)
        self.stats["scratch_dual_edges"] += len(self.out_pending) == 2

    def write_shared(self, packet):
        slot, index, word = packet
        address = base.RESULT_BASE + index // 2
        assert address not in self.out_memory and address not in self.shared
        self.out_memory[address] = word
        slot.committed += 1
        self.output_written += 1
        self.marks.setdefault("first_physical_commit", self.cycle)
        self.marks["final_physical_commit"] = self.cycle
        if slot.committed == slot.words:
            assert slot.reads == slot.words and self.slots[0].popleft() is slot
            for row in range(slot.rows):
                for col in range(16):
                    bank, addr = slot.cell(row, col)
                    assert self.result_banks[bank][addr][0] == slot.sequence
                    self.result_banks[bank][addr] = None

    def transfer_results(self, ports, bankset, host_dual):
        if self.write_ack is not None:
            assert self.write_ack == self.cycle - 1
            self.stats["write_ack"] += 1
            self.write_ack = None
            self.record("ack")
            if self.stats["write_ack"] == RESULT_WORDS:
                self.marks["final_ack"] = self.cycle
        returned = self.out_pending
        self.out_pending = []
        if self.out_held:
            packet = self.out_held[0]
            bank = base.physical_bank(base.RESULT_BASE + packet[1] // 2)
            assert 4 <= bank <= 7
            if bank not in bankset:
                bankset.add(bank)
                self.out_held.popleft()
                self.write_shared(packet)
                self.write_ack = self.cycle
                self.record("write", base.RESULT_BASE + packet[1] // 2)
                if host_dual:
                    self.record("triple")
            else:
                self.stats["result_shared_bank_wait"] += 1
        self.out_held.extend(returned)
        self.prefetch_output(ports)

    def retire_pages(self):
        if self.oldest == TILES:
            return
        page = self.pages[self.oldest % 2]
        if page is not None and page.tile == self.oldest and page.emitted == 17:
            assert page.next_unit == UNITS and page.written == self.layout.sizes[page.tile]
            self.pages[self.oldest % 2] = None
            self.record("page_release", self.oldest)
            self.oldest += 1

    def summary(self, complete):
        row = super().summary(complete)
        row["slot_peak"] = self.ring_peak[0]
        row["last_scratch"] = self.events["scratch"][-1] if self.events["scratch"] else None
        return row

    def run(self):
        self.weight_banks = [[None] * 128 for _ in range(16)]
        self.weight_q = [None] * 16
        self.acc = [{}, {}]
        last_progress = -1
        last_cycle = 0
        while "final_ack" not in self.marks:
            self.tokens[self.cycle % 64] = None
            result_ports = set()
            self.finish_output_column(result_ports)
            self.issue(result_ports)
            weight_ports = self.mac()
            self.load_private(result_ports, weight_ports)
            self.transfer(result_ports)
            self.retire_pages()
            progress = sum(len(self.events[name]) for name in
                           ("host", "source_fire", "load", "issue", "quant", "scratch", "write"))
            if progress != last_progress:
                last_progress = progress
                last_cycle = self.cycle
            if self.cycle - last_cycle > 128:
                return self.summary(False)
            self.cycle += 1
        assert self.issue_count == ISSUES and self.mac_operations == 25344 * 64
        assert self.host_index == 11690 and self.read_index == 11680 and self.input_written == INPUT_WORDS
        assert self.stats["host_payload_commits"] == len(self.events["source_return"]) == 11680
        assert self.stats["weight_macro_reads"] == 147456 and self.stats["weight_write64"] == 4096
        assert self.stats["quant_halfwords"] == self.stats["result_macro_reads"] == 25344
        assert self.output_written == len(self.events["ack"]) == RESULT_WORDS
        assert not any(self.slots) and self.oldest == TILES
        for index in range(0, 25344, 2):
            assert base.halves(self.out_memory[base.RESULT_BASE + index // 2]) == tuple(self.golden[index:index+2])
        return self.summary(True)


def run_case(args):
    lanes, case, startup = args
    return SixRowTask(case, lanes, startup).run()


def main():
    startup, edges, identities = observation()
    frozen = Task(0, 16, startup)
    assert frozen.run()["cold_cycles"] == 28093
    assert all(frozen.events[name] == trace for name, trace in edges.items())
    assert all(frozen.identities_by_event[name] == trace for name, trace in identities.items())
    assert len({mapped_word(address) for address in range(1 << 17)}) == 1 << 17
    if "--first" in sys.argv:
        for lanes in (1, 2):
            row = run_case((lanes, 0, startup))
            print(lanes, {key: row[key] for key in ("complete", "cold_cycles", "first_issue", "last_issue",
                   "last_scratch", "final_physical_commit", "final_ack", "slot_peak")}, row["counters"], flush=True)
        return
    REPORT.mkdir(parents=True, exist_ok=True)
    results = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for lanes in (1, 2):
            rows = list(pool.map(run_case, ((lanes, case, startup) for case in range(12))))
            total = sum(row["cold_cycles"] for row in rows) if all(row["complete"] for row in rows) else None
            results[str(lanes)] = dict(total_cycles=total, throughput=1_800_000_000 / total if total else None,
                                       passes=total is not None and total <= TARGET, rows=rows)
            print(lanes, total, results[str(lanes)]["throughput"], [row["cold_cycles"] for row in rows], flush=True)
    winner = next((int(lanes) for lanes in results if results[lanes]["passes"]), None)
    output = dict(start_edge=startup["start"], target_cycles=TARGET, selected=winner, model_results=results)
    (REPORT / "model-result.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("SCREEN", winner, flush=True)


if __name__ == "__main__":
    main()

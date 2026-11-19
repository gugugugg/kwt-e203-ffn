"""Cold-task comparison of the two fixed 128-MAC shapes."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sixteen_reference", HERE.parent / "trb_6x16/model.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
INPUT_WORDS, RESULT_WORDS = reference.INPUT_WORDS, reference.RESULT_WORDS
Layout, ResultSlot, SixRowTask = reference.Layout, reference.ResultSlot, reference.SixRowTask
base, observation = reference.base, reference.observation
from supply_study import SupplyTask

ROOT = HERE.parents[1]
REPORT = ROOT / "reports/optimization/ffn_trb_128mac"
REFERENCE_LOG = (ROOT / "reports/optimization/ffn_trb_6x16/received/arbitration-smoke/native-evidence"
                 / "reports/optimization/complete_soc/ffn_trb_sixteen/run_01.log")
TARGET = 180000
RESULT_CREDITS = 34


class WideSlot(ResultSlot):
    def __init__(self, index, tile, group, sequence, layout, rows):
        super().__init__(0, index, tile, group, sequence, layout)
        self.tile_rows = rows

    @property
    def rows(self):
        return min(self.tile_rows, 99 - self.group * self.tile_rows)

    @property
    def words(self):
        return self.rows * (self.width // 2)

    def cell(self, row, col):
        stripe, local = divmod(col, 16)
        return (row + local + 4 * stripe) % 8, self.index * 16 + local


class WideTask(SixRowTask):
    def __init__(self, case, rows, startup):
        # Keep the validated shared-bank transport and frozen numerical fixtures.
        super().__init__(case, 2, startup)
        old_inputs = {}
        for address in range(INPUT_WORDS):
            ids = self.identities[2 * address:2 * address + 2]
            old_inputs.update(zip(ids, base.halves(self.source[address])))
        self.rows = rows
        self.width = 128 // rows
        self.layout = Layout(self.width)
        self.source, _, _ = self.layout.pack(case)
        self.pairs = 96 // (2 * rows)
        self.tail_group = 2 * self.pairs
        self.first_unit_words = 64 * rows
        self.output_credit_limit = RESULT_CREDITS
        self.input_banks = [[None] * 1024 for _ in range(2 * rows)]
        self.result_banks = [[None] * 128 for _ in range(8)]
        self.weight_banks = [[None] * 128 for _ in range(self.width)]
        self.weight_q = [None] * self.width
        self.acc = [{}, {}]

        # Two words per side, alternating sides even for eight-row groups.
        self.identities = [
            (2 * rows * pair + rows * side + lane, k)
            for pair in range(self.pairs)
            for k in range(64)
            for first_lane in range(0, rows, 4)
            for side in range(2)
            for lane in range(first_lane, first_lane + 4)
        ]
        self.identities.extend((row, k) for k in range(64) for row in range(96, 99))
        assert len(self.identities) == len(set(self.identities)) == 6336
        for address in range(INPUT_WORDS):
            first, second = self.identities[2 * address:2 * address + 2]
            self.source[address] = base.packed(old_inputs[first], old_inputs[second])
        p0_end = base.PARAMETER_BASE + self.layout.sizes[0]
        self.order = (list(range(self.first_unit_words)) +
                      list(range(base.PARAMETER_BASE, p0_end)) +
                      list(range(self.first_unit_words, INPUT_WORDS)) +
                      list(range(p0_end, base.PARAMETER_BASE + 8512)))
        self.host_order = [(0, self.source[0])] + startup["controls"]
        self.host_order.extend((address, self.source[address]) for address in self.order if address)
        assert len(self.order) == len(set(self.order)) == 11680

    def input_cell(self, row, k):
        group, lane = divmod(row, self.rows)
        return group % 2 * self.rows + lane, group // 2 * 64 + k

    def source_candidate(self):
        address = super().source_candidate()
        if address is None:
            return None
        if self.events["source_fire"] and self.events["source_fire"][-1] == self.cycle:
            previous = (self.identities_by_event["source_fire"][-1][0] - 0xa0000000) // 4
            if address != previous + 1 or (address >= base.PARAMETER_BASE and self.layout.param(address)[1] == 0):
                return None
        return address

    def reserve(self, page, pair):
        slots = []
        for group in range(2 * pair, min(2 * pair + 2, self.tail_group + 1)):
            index = self.next_slot[0]
            assert all(slot.index != index for slot in self.slots[0])
            slot = WideSlot(index, page.tile, group, self.slot_sequence, self.layout, self.rows)
            self.slot_sequence += 1
            self.slots[0].append(slot)
            slots.append(slot)
            self.next_slot[0] = (index + 1) % 8
        self.ring_peak[0] = max(self.ring_peak[0], len(self.slots[0]))
        return tuple(slots)

    def start_unit(self):
        if self.cycle <= self.kickoff:
            return "prelude"
        tile = self.oldest
        if tile == len(self.layout.widths):
            return "pipeline_or_output"
        old = self.pages[tile % 2]
        if old is not None and old.next_unit == self.pairs + 1:
            tile += 1
        if tile == len(self.layout.widths):
            return "pipeline_or_output"
        page = self.pages[tile % 2]
        if page is None or page.next_unit > self.pairs or page.written != self.layout.sizes[tile]:
            return "weight_page"
        pair = page.next_unit
        if self.input_written < min((pair + 1) * self.first_unit_words, INPUT_WORDS):
            return "input_prefix"
        required = 1 if pair == self.pairs else 2
        if len(self.slots[0]) + required > 8:
            return "result_slots"
        if required == 2 and self.phase():
            return "pair_phase"
        page.next_unit += 1
        self.unit = base.Unit(page, pair, self.reserve(page, pair))
        self.unit_history.append([self.cycle, tile, pair])
        return None

    def issue(self, ports):
        if self.unit is None:
            reason = self.start_unit()
            if reason:
                self.stats["issue_wait_" + reason] += 1
                return
        unit = self.unit
        paired = unit.pair != self.pairs
        index = unit.index
        slot = unit.slots[index % 2] if paired else unit.slots[0]
        k = index // 2 if paired else index
        values = []
        for row in range(slot.group * self.rows, slot.group * self.rows + slot.rows):
            bank, address = self.input_cell(row, k)
            stored, value = self.input_banks[bank][address]
            assert stored == row and bank not in ports
            ports.add(bank)
            values.append(value)
        self.tokens[self.cycle % 64] = base.Token(slot, k, tuple(values), not paired or index % 2 == 0)
        self.issue_count += 1
        self.stats["input_macro_reads"] += len(values)
        self.record("issue", slot.tile, unit.pair, index)
        unit.index += 1
        if unit.index == (128 if paired else 64):
            self.unit = None

    def mac(self):
        weight_ports = set()
        for col in range(self.width):
            age = 1 + 2 * (col % 16)
            read = self.tokens[(self.cycle - age) % 64] if self.cycle >= age else None
            execute = self.tokens[(self.cycle - age - 1) % 64] if self.cycle > age else None
            if execute:
                self.marks.setdefault("first_mac", self.cycle)
                slot, k = execute.slot, execute.inner
                page = self.pages[slot.tile % 2]
                assert page is not None and page.tile == slot.tile
                tile, inner, weight = self.weight_q[col]
                assert (tile, inner) == (slot.tile, k)
                context = self.acc[slot.group % 2]
                results = []
                for row, value in enumerate(execute.values):
                    key = (row, col)
                    prior = context.get(key)
                    if k == 0:
                        assert prior is None
                        previous = page.bias[col]
                    else:
                        assert prior[:2] == (slot.sequence, k)
                        previous = prior[2]
                    result = base.baseline.q16.signed(previous + value * weight, 36)
                    self.mac_operations += 1
                    if k == 63:
                        results.append(base.baseline.q16.rne(result, page.shift[col]))
                        context.pop(key)
                    else:
                        context[key] = (slot.sequence, k + 1, result)
                if results:
                    self.quant.setdefault(self.cycle + 2, []).append((slot, col, tuple(results)))
            if read and read.weight_read:
                address = 64 * (read.slot.tile % 2) + read.inner
                value = self.weight_banks[col][address]
                assert value[:2] == (read.slot.tile, read.inner)
                self.weight_q[col] = value
                weight_ports.add(col)
        self.stats["weight_macro_reads"] += len(weight_ports)
        return weight_ports

    def finish_output_column(self, ports):
        events = self.quant.pop(self.cycle, [])
        if events:
            self.stats["quant_active_edges"] += 1
        for slot, col, values in events:
            stripes = self.width // 16
            assert col == slot.columns // stripes + 16 * (slot.columns % stripes)
            assert len(values) == slot.rows
            for row, value in enumerate(values):
                bank, address = slot.cell(row, col)
                assert bank not in ports and self.result_banks[bank][address] is None
                self.result_banks[bank][address] = slot.sequence, value
                ports.add(bank)
            slot.columns += 1
            self.stats["quant_halfwords"] += len(values)
            self.marks["last_emit"] = self.cycle
            if slot.columns == self.width:
                slot.completed_edge = self.cycle
                self.pages[slot.tile % 2].emitted += 1
            self.record("quant", col, slot.side)
        if len(ports) == 8:
            self.stats["quant_all_bank_edges"] += 1

    def load_private(self, input_ports, weight_ports):
        if not self.incoming or self.incoming[0][0] >= INPUT_WORDS:
            return SupplyTask.load_private(self, set(), weight_ports)
        assert self.weight_pack is None
        budget = 1 if self.input_written >= 3072 else 2
        writes = 0
        for _ in range(budget):
            if not self.incoming or self.incoming[0][0] >= INPUT_WORDS:
                break
            address, data = self.incoming[0]
            assert address == self.input_written
            rows = self.identities[2 * address:2 * address + 2]
            cells = [self.input_cell(row, k) for row, k in rows]
            banks = {bank for bank, _ in cells}
            assert len(banks) == 2
            if banks & input_ports:
                self.stats["input_write_wait"] += 1
                break
            for (row, _), (bank, index), value in zip(rows, cells, base.halves(data)):
                assert self.input_banks[bank][index] is None
                self.input_banks[bank][index] = row, value
            input_ports.update(banks)
            self.incoming.popleft()
            self.input_written += 1
            writes += 1
            self.record("load")
        self.stats["private_input_multiword_edges"] += writes == 2
        if self.input_written == INPUT_WORDS:
            self.marks["input_commit_edge"] = self.cycle

    def prefetch_output(self, ports):
        slot = next((slot for slot in self.slots[0] if slot.reads < slot.words), None)
        if slot is None or slot.completed_edge is None or slot.completed_edge == self.cycle:
            return
        if self.output_credit_limit - len(self.out_held) < 2:
            self.stats["scratch_credit_blocked_edges"] += 1
            return
        row, pair = divmod(slot.reads, self.width // 2)
        assert pair % 2 == 0
        cells = [slot.cell(row, 2 * pair + half) for half in range(4)]
        banks = {bank for bank, _ in cells}
        assert len(banks) == 4
        if banks & ports:
            self.stats["scratch_bank_conflict_edges"] += 1
            return
        values = []
        for bank, address in cells:
            owner, value = self.result_banks[bank][address]
            assert owner == slot.sequence
            values.append(value)
        index = (self.rows * slot.group + row) * 256 + self.width * slot.tile + 2 * pair
        assert tuple(values) == tuple(self.golden[index:index + 4])
        self.out_pending.extend((slot, index + half, base.packed(*values[half:half + 2])) for half in (0, 2))
        slot.reads += 2
        self.stats["result_macro_reads"] += 4
        self.stats["scratch_dual_edges"] += 1
        ports.update(banks)
        self.record("scratch", slot.side)

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
                for col in range(self.width):
                    bank, addr = slot.cell(row, col)
                    assert self.result_banks[bank][addr][0] == slot.sequence
                    self.result_banks[bank][addr] = None

    def retire_pages(self):
        if self.oldest < len(self.layout.widths):
            page = self.pages[self.oldest % 2]
            if page is not None and page.tile == self.oldest and page.emitted == self.tail_group + 1:
                assert page.next_unit == self.pairs + 1 and page.written == self.layout.sizes[page.tile]
                self.pages[self.oldest % 2] = None
                self.record("page_release", self.oldest)
                self.oldest += 1

    def run(self):
        while "final_ack" not in self.marks:
            self.tokens[self.cycle % 64] = None
            input_ports, result_ports = set(), set()
            self.finish_output_column(result_ports)
            self.issue(input_ports)
            weight_ports = self.mac()
            self.load_private(input_ports, weight_ports)
            self.transfer(result_ports)
            self.retire_pages()
            self.cycle += 1
            if self.cycle == 30000:
                return self.summary(False)
        assert self.issue_count == len(self.layout.widths) * (self.pairs * 128 + 64)
        assert self.mac_operations == 25344 * 64
        assert self.host_index == 11690 and self.read_index == 11680 and self.input_written == INPUT_WORDS
        assert self.stats["host_setup_commits"] == 10
        assert self.stats["host_payload_commits"] == len(self.events["source_return"]) == 11680
        assert self.stats["weight_macro_reads"] == (self.pairs + 1) * 256 * 64
        assert self.stats["weight_write64"] == 4096
        assert self.stats["quant_halfwords"] == self.stats["result_macro_reads"] == 25344
        assert self.output_written == len(self.events["ack"]) == RESULT_WORDS
        assert not any(self.slots) and self.oldest == len(self.layout.widths)
        for index in range(0, 25344, 2):
            assert base.halves(self.out_memory[base.RESULT_BASE + index // 2]) == tuple(self.golden[index:index + 2])
        return self.summary(True)


def run_case(args):
    rows, case, startup = args
    return WideTask(case, rows, startup).run()


def calibrated_startup():
    startup, _, _ = observation()
    reference = SixRowTask(0, 1, startup).run()
    measured = {
        key: int(re.search(key + r"=(\d+)", REFERENCE_LOG.read_text(encoding="utf-8"))[1])
        for key in ("cycles", "last_commit", "last_ack")
    }
    assert (reference["cold_cycles"], reference["final_physical_commit"], reference["final_ack"]) == (
        measured["cycles"], measured["last_commit"], measured["last_ack"])
    return startup, measured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", action="store_true")
    args = parser.parse_args()
    startup, measured = calibrated_startup()
    results = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for rows in (4, 8):
            name = "%dx%d" % (rows, 128 // rows)
            cases = list(pool.map(run_case, ((rows, case, startup) for case in range(1 if args.first else 12))))
            total = sum(row["cold_cycles"] for row in cases) if all(row["complete"] for row in cases) else None
            throughput = len(cases) * 150_000_000 / total if total else None
            results[name] = dict(total_cycles=total, throughput=throughput, cases=cases)
            print(name, total, throughput, [(row["first_issue"], row["final_physical_commit"], row["slot_peak"])
                                            for row in cases], flush=True)
    if not args.first:
        chosen = results["4x32"]["total_cycles"]
        REPORT.mkdir(parents=True, exist_ok=True)
        (REPORT / "model-result.json").write_text(json.dumps(dict(
            measured_6x16_calibration=measured, target_cycles=TARGET, result_credits=RESULT_CREDITS,
            passes_4x32=chosen is not None and chosen <= TARGET, models=results), indent=2) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()

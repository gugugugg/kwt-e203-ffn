"""Causal screen for the 4x32 paired-product schedule and correction ports."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/optimization/ffn_trb_pair_mac"
spec = importlib.util.spec_from_file_location("wide_reference", ROOT / "scripts/trb_128mac/model.py")
wide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wide)
base = wide.base
signed = base.baseline.q16.signed
rne = base.baseline.q16.rne


class PairedTask(wide.WideTask):
    def __init__(self, case, startup):
        super().__init__(case, 4, startup)
        self.evens = {}
        self.commit = {}
        self.frontend = set()
        self.restores = {}
        self.row_evens = {}
        self.row_sums = {}
        self.row_store = {}
        self.row_writes = deque()
        self.row_queue_peak = 0
        self.cache_requests = deque()
        self.cache_owner = None
        self.cache = {}
        self.cache_return = None
        self.weight_evens = {}
        self.weight_sums = {}
        self.correction_ops = 0
        self.slice_events = {}
        self.correction_events = {}
        self.correction_reads = []
        self.physical_main_products = 0
        self.last_preadder = -1

    def issue(self, ports):
        if self.unit is None:
            reason = self.start_unit()
            if reason:
                self.stats["issue_wait_" + reason] += 1
                return
            unit = self.unit
            rows = tuple(row for slot in unit.slots
                         for row in range(4 * slot.group, 4 * slot.group + slot.rows))
            self.cache_requests.append((unit.slots[0].sequence, rows))
            if len(unit.slots) == 1:
                self.stats["tail_entry_bubble"] += 1
                return
        super().issue(ports)

    def correction_memory(self):
        if self.cache_return is not None:
            row, value = self.cache_return
            self.cache[row] = value
            self.cache_return = None
        if self.row_writes:
            row, value = self.row_writes.popleft()
            assert row not in self.row_store
            self.row_store[row] = value
            self.stats["correction_row_writes"] += 1
            return
        if self.cache_owner is None and self.cache_requests:
            self.cache_owner, _ = self.cache_requests[0]
        if self.cache_owner is None:
            return
        owner, rows = self.cache_requests[0]
        assert owner == self.cache_owner
        for row in rows:
            if row not in self.cache:
                if row in self.row_store:
                    self.cache_return = row, self.row_store[row]
                    self.correction_reads.append((self.cycle, row, rows.index(row)))
                    self.stats["correction_row_reads"] += 1
                else:
                    self.stats["correction_prefetch_wait"] += 1
                break

    def correction_product(self, even, odd, role, index, k, bias):
        self.correction_ops += 1
        self.correction_events.setdefault(self.cycle, []).append((role, index, k, even, odd, bias))
        assert len(self.correction_events[self.cycle]) <= 8
        return even * odd

    def load_private(self, input_ports, weight_ports):
        before_input = self.input_written
        before_page = {page.tile: page.written for page in self.pages if page}
        super().load_private(input_ports, weight_ports)
        for address in range(before_input, self.input_written):
            for row, k in self.identities[2 * address:2 * address + 2]:
                bank, offset = self.input_cell(row, k)
                found, value = self.input_banks[bank][offset]
                assert found == row
                if k % 2 == 0:
                    assert row not in self.row_evens
                    self.row_evens[row] = value
                else:
                    correction = self.correction_product(self.row_evens.pop(row), value, 0, row, k, 0)
                    value = signed(self.row_sums.get(row, 0) - correction, 36)
                    if k == 63:
                        self.row_sums.pop(row, None)
                        self.row_writes.append((row, value))
                    else:
                        self.row_sums[row] = value
        self.row_queue_peak = max(self.row_queue_peak, len(self.row_writes))
        assert self.row_queue_peak <= 8
        for page in self.pages:
            if not page:
                continue
            for offset in range(max(40, before_page[page.tile]), page.written):
                k, word = divmod(offset - 40, 16)
                for col in (2 * word, 2 * word + 1):
                    tile, inner, weight = self.weight_banks[col][64 * (page.tile % 2) + k]
                    assert (tile, inner) == (page.tile, k)
                    key = (tile, col)
                    if k % 2 == 0:
                        assert key not in self.weight_evens
                        self.weight_evens[key] = weight
                    else:
                        correction = self.correction_product(self.weight_evens.pop(key), weight, 1,
                                                             tile*32+col, k, page.bias[col])
                        value = signed(self.weight_sums.get(key, page.bias[col]) - correction, 36)
                        self.weight_sums[key] = value

    def mac(self):
        ports = set()
        # Commit the previous edge's front-end pair before considering any new
        # issue. A context identity also protects the old value at retirement.
        for slot, col, row, k, product in self.commit.pop(self.cycle, []):
            context = self.acc[slot.group % 2]
            key = row, col
            previous = context.get(key)
            if k == 1:
                assert previous is None
                value = product
            else:
                assert previous[:2] == (slot.sequence, k)
                value = previous[2] + product
            context[key] = slot.sequence, k + 2, signed(value, 36)
            self.physical_main_products += 1
            self.mac_operations += 2
            self.marks.setdefault("first_mac", self.cycle)

        for slot, col in self.restores.pop(self.cycle, []):
            owner, rows = self.cache_requests[0]
            assert self.cache_owner == owner and slot.sequence in (owner, owner + (len(rows) == 8))
            context = self.acc[slot.group % 2]
            page = self.pages[slot.tile % 2]
            assert page is not None and page.tile == slot.tile
            values = []
            for row in range(slot.rows):
                seq, k, value = context.pop((row, col))
                assert (seq, k) == (slot.sequence, 65)
                adjusted = signed(value + self.weight_sums[slot.tile, col] + self.cache[4 * slot.group + row], 36)
                values.append(rne(adjusted, page.shift[col]))
            self.quant.setdefault(self.cycle + 2, []).append((slot, col, tuple(values)))
            if col == 31 and (slot.group == 24 or slot.group % 2 == 1):
                self.cache_requests.popleft()
                self.cache_owner = None
                self.cache.clear()

        self.frontend = {key for key in self.frontend if key[0] >= self.cycle}
        for col in range(self.width):
            age = 1 + 2 * (col % 16)
            read = self.tokens[(self.cycle - age) % 64] if self.cycle >= age else None
            execute = self.tokens[(self.cycle - age - 1) % 64] if self.cycle > age else None
            if execute:
                slot, k = execute.slot, execute.inner
                tile, inner, weight = self.weight_q[col]
                assert (tile, inner) == (slot.tile, k)
                key = slot.sequence, col
                if col in (0, 16):
                    self.slice_events.setdefault(self.cycle, {})[col] = (slot, k, execute.values, weight)
                if k % 2 == 0:
                    assert key not in self.evens
                    self.evens[key] = execute.values, weight
                else:
                    even_values, even_weight = self.evens.pop(key)
                    first = self.cycle + int(slot.group != 24 and slot.group % 2 == 1)
                    for row, (even, odd) in enumerate(zip(even_values, execute.values)):
                        when = first + row // 2
                        resource = when, col, row % 2
                        assert resource not in self.frontend, (when, col, row, k)
                        self.frontend.add(resource)
                        left, right = even + weight, odd + even_weight
                        assert signed(left, 17) == left and signed(right, 17) == right
                        self.commit.setdefault(when + 1, []).append((slot, col, row, k, left * right))
                    if k == 63:
                        self.restores.setdefault(self.cycle + 4, []).append((slot, col))
            if read and read.weight_read:
                address = 64 * (read.slot.tile % 2) + read.inner
                value = self.weight_banks[col][address]
                assert value[:2] == (read.slot.tile, read.inner)
                self.weight_q[col] = value
                ports.add(col)
        self.stats["weight_macro_reads"] += len(ports)
        return ports

    def finish_output_column(self, ports):
        self.correction_memory()
        super().finish_output_column(ports)

    def run(self):
        result = super().run()
        if result["complete"]:
            assert self.physical_main_products == 811008 and self.correction_ops == 11360
            assert not any((self.evens, self.commit, self.restores, self.row_evens, self.row_writes,
                            self.row_sums, self.cache_requests, self.weight_evens))
            result.update(paired_main_products=self.physical_main_products,
                          correction_products=self.correction_ops, correction_row_queue_peak=self.row_queue_peak)
        return result


def run_case(args):
    case, startup, paired = args
    task = PairedTask(case, startup) if paired else wide.WideTask(case, 4, startup)
    return task.run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", action="store_true")
    args = parser.parse_args()
    startup, calibration = wide.calibrated_startup()
    count = 1 if args.first else 12
    rows = {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for paired in (False, True):
            name = "paired" if paired else "baseline"
            cases = list(pool.map(run_case, ((i, startup, paired) for i in range(count))))
            assert all(row["complete"] for row in cases), (name, cases)
            total = sum(row["cold_cycles"] for row in cases)
            rows[name] = dict(cases=cases, cycles=total, throughput=count * 150_000_000 / total)
            print(name, [row["cold_cycles"] for row in cases], total, rows[name]["throughput"], flush=True)
    assert all((r["cold_cycles"], r["final_physical_commit"], r["final_ack"]) == (14344, 14343, 14344)
               for r in rows["baseline"]["cases"])
    if not args.first:
        REPORT.mkdir(parents=True, exist_ok=True)
        record = dict(calibration_6x16=calibration, target_cycles=180000, results=rows,
                      passes_cycles=rows["paired"]["cycles"] <= 180000)
        (REPORT / "model-result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()


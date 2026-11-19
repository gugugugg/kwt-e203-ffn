"""Cycle and value model for the single T+R+B two-page streaming candidate."""

import argparse
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/optimization/ffn_trb_twopage"
spec = importlib.util.spec_from_file_location("trb_k8_model", ROOT / "scripts/trb_k8/model.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)

INPUT_WORDS = 3168
PACKET_WORDS = 532
PARAMETER_BASE = 0x8000
RESULT_BASE = 0x4000
INPUT_PREFIX = 1024
CYCLE_TARGET = 339622
RESULT_COUNT = 99 * 256
CONTEXTS = 13
TILES = 16
RING_LIMIT = (12, 16)
CLOCK = 150_000_000
DATA_WORDS = INPUT_WORDS + TILES * PACKET_WORDS


def physical_bank(word):
    if word < 0x2000 or PARAMETER_BASE <= word < PARAMETER_BASE + 0x2000:
        word = (word & ~0x1001) | ((word & 1) << 12) | ((word >> 12) & 1)
    return word >> 12


def halves(word):
    return baseline.q16.signed(word & 65535, 16), baseline.q16.signed(word >> 16, 16)


def packed(low, high):
    return (low & 65535) | ((high & 65535) << 16)


def input_location(row, inner):
    return row % 8, row // 8 * 64 + inner


@dataclass
class Slot:
    side: int
    index: int
    tile: int
    group: int
    sequence: int
    columns: int = 0
    reads: int = 0
    committed: int = 0

    @property
    def words(self):
        return 24 if self.group == 24 else 32

    def cell(self, row, col):
        base = (832, 768)[self.side]
        return 4 * self.side + (row ^ (col & 1)), base + 16 * self.index + col


@dataclass
class Page:
    tile: int
    written: int = 0
    next_unit: int = 0
    emitted: int = 0

    def __post_init__(self):
        self.bias = [None] * 16
        self.shift = [None] * 16


@dataclass
class Unit:
    page: Page
    pair: int
    slots: tuple
    index: int = 0

    @property
    def length(self):
        return 64 if self.pair == 12 else 128


@dataclass
class Token:
    slot: Slot
    inner: int
    values: tuple
    weight_read: bool


def payload(case):
    x, weights, bias, shifts = baseline.q16.q8.m3.r3o.vectors(case)
    # Alternate the target bank sets inside each full eight-row unit. Once
    # aligned, the sequential DMA stream can use the side not read by the MAC.
    order_in_pair = (0, 1, 4, 5, 2, 3, 6, 7)
    identities = [(first + lane, k) for first in range(0, 96, 8) for k in range(64)
                  for lane in order_in_pair]
    identities.extend((row, k) for k in range(64) for row in range(96, 99))
    source = {i: packed(x[r0 * 64 + k0], x[r1 * 64 + k1])
              for i, ((r0, k0), (r1, k1)) in enumerate(zip(identities[::2], identities[1::2]))}
    packets = []
    for tile in range(TILES):
        col = 16 * tile
        words = [v & 0xffffffff for v in bias[col:col+16]]
        assert all(baseline.q16.signed(word, 32) == v for word, v in zip(words, bias[col:col+16]))
        for offset in range(0, 16, 4):
            words.append(sum((shifts[col + offset + i] & 255) << (i * 8) for i in range(4)))
        for k in range(64):
            offset = k * 256 + col
            words.extend(packed(weights[offset + i], weights[offset + i + 1]) for i in range(0, 16, 2))
        addresses = list(range(PARAMETER_BASE + tile * PACKET_WORDS,
                               PARAMETER_BASE + (tile + 1) * PACKET_WORDS))
        source.update(zip(addresses, words))
        packets.append(addresses)
    order = packets[0] + list(range(INPUT_PREFIX)) + packets[1] + list(range(INPUT_PREFIX, INPUT_WORDS))
    order.extend(word for packet in packets[2:] for word in packet)
    assert len(order) == len(set(order)) == DATA_WORDS
    return source, order, identities


class StreamingTask:
    def __init__(self, case, controls, kickoff, host_start, cpu_setup):
        self.case, self.cycle = case + 1, 0
        self.source, self.order, self.identities = payload(case)
        _, self.golden = baseline.t.m3.sr.frozen_image(case)
        self.host_order = [(0, self.source[0])] + list(controls)
        self.host_order.extend((addr, self.source[addr]) for addr in self.order if addr)
        assert len(self.host_order) == DATA_WORDS + 10
        self.kickoff, self.host_start = kickoff, host_start
        self.cpu_setup = {cmd["accept"]: cmd for cmd in cpu_setup}
        self.cpu_reserved = {edge for cmd in cpu_setup
                             for edge in range(cmd["accept"], cmd["response"] + 1)}
        self.shared = {}
        self.host_index = self.read_index = self.input_written = 0
        self.pages = [None, None]
        self.weight_banks = [[None] * 128 for _ in range(16)]
        self.input_banks = [[None] * 1024 for _ in range(8)]
        self.slots = [deque(), deque()]
        self.next_slot = [0, 0]
        self.slot_sequence = 0
        self.oldest = 0
        self.unit = None
        self.tokens = [None] * 64
        self.quant = {}
        self.weight_q = [None] * 16
        self.acc = [[[None] * 16 for _ in range(4)] for _ in range(2)]
        self.mac_operations = 0
        self.bus_pending = None
        self.incoming = deque()
        self.weight_pack = None
        self.out_pending = None
        self.out_held = deque()
        self.out_memory = {}
        self.output_written = 0
        self.preempt = False
        self.blocked_sides = set()
        self.ring_peak = [0, 0]
        self.read_peak = self.output_credit_peak = 0
        self.stats = Counter()
        self.marks = {}
        self.page_history = []
        self.unit_history = []
        self.issue_count = 0
        self.early_switches = 0
        self.max_last_issue = -64

    def ring_ready(self, page):
        if page.next_unit == 12:
            return len(self.slots[1]) < RING_LIMIT[1]
        return all(len(self.slots[s]) < RING_LIMIT[s] for s in range(2))

    def reserve(self, page, pair):
        slots = []
        for group in range(2 * pair, min(2 * pair + 2, 25)):
            side = (group & 1) ^ 1
            index = self.next_slot[side]
            assert all(slot.index != index for slot in self.slots[side])
            slot = Slot(side, index, page.tile, group, self.slot_sequence)
            self.slot_sequence += 1
            self.slots[side].append(slot)
            self.next_slot[side] = (index + 1) % RING_LIMIT[side]
            self.ring_peak[side] = max(self.ring_peak[side], len(self.slots[side]))
            slots.append(slot)
        return tuple(slots)

    def start_unit(self):
        if self.cycle < self.kickoff:
            return "prelude"
        if self.oldest == TILES:
            return "pipeline_or_output"
        reasons = []
        older = self.pages[self.oldest % 2]
        for page in sorted((p for p in self.pages if p is not None), key=lambda p: p.tile):
            if page.tile > self.oldest and older is not None and older.next_unit < CONTEXTS:
                words_to_old = min((older.next_unit + 1) * 256, INPUT_WORDS) - self.input_written
                # A younger unit holds both contexts until k=63. Only use it
                # to fill a whole older input gap, so it cannot delay an
                # older unit that could otherwise become ready in that time.
                if 0 < words_to_old < (64 if page.next_unit == 12 else 128):
                    continue
            if page.next_unit == CONTEXTS:
                continue
            pair = page.next_unit
            # The first paired unit can overlap at most 128 remaining words
            # on the 32-bit source interface. Its individual k vectors still
            # have to be committed before either context issues.
            required = PACKET_WORDS if pair == 12 else PACKET_WORDS - 128
            if page.written < required:
                reasons.append("weight_page")
                continue
            if self.input_written < min((pair + 1) * 256, INPUT_WORDS):
                reasons.append("input_prefix")
                continue
            if not self.ring_ready(page):
                sides = (1,) if pair == 12 else (0, 1)
                self.blocked_sides.update(s for s in sides if len(self.slots[s]) == RING_LIMIT[s])
                reasons.append("result_slots")
                continue
            if pair != 12 and self.cycle % 2:
                reasons.append("pair_phase")
                continue
            page.next_unit += 1
            self.unit = Unit(page, pair, self.reserve(page, pair))
            self.unit_history.append([self.cycle, page.tile, pair])
            self.early_switches += page.tile > self.oldest
            return None
        return reasons[0] if reasons else "weight_page_or_pipeline"

    def issue(self, ports):
        self.blocked_sides.clear()
        if self.unit is None:
            reason = self.start_unit()
            if reason:
                self.stats["issue_wait_" + reason] += 1
                return
        unit = self.unit
        paired = unit.pair != 12
        index = unit.index
        slot = unit.slots[index % 2] if paired else unit.slots[0]
        k = index // 2 if paired else index
        if unit.page.written < 20 + 8 * (k + 1):
            assert not paired or index % 2 == 0
            self.stats["issue_wait_weight_vector"] += 1
            return
        # Emit the last three-row unit's columns into side B on even edges.
        # The following paired unit reads side A on those edges.
        if not paired and k == 63 and self.cycle % 2:
            self.stats["issue_wait_tail_phase"] += 1
            return
        rows = range(4 * slot.group, min(4 * slot.group + 4, 99))
        cells = [input_location(r, k) for r in rows]
        if any(bank in ports for bank, _ in cells):
            assert not paired or index % 2 == 0
            self.stats["issue_wait_input_quant_bank"] += 1
            return
        if paired and index % 2 == 0:
            tomorrow = self.quant.get(self.cycle + 1)
            if self.cycle % 2 or (tomorrow and tomorrow[0].side == 1):
                self.stats["issue_wait_pair_bank_or_phase"] += 1
                return
        values = []
        for bank, address in cells:
            cell = self.input_banks[bank][address]
            assert cell is not None
            r, value = cell
            assert input_location(r, k) == (bank, address)
            values.append(value)
            ports.add(bank)
        self.tokens[self.cycle % 64] = Token(slot, k, tuple(values), not paired or index % 2 == 0)
        self.max_last_issue = self.cycle
        self.issue_count += 1
        self.stats["input_macro_reads"] += len(values)
        unit.index += 1
        if unit.index == unit.length:
            self.unit = None

    def finish_output_column(self, ports):
        event = self.quant.pop(self.cycle, None)
        if event is None:
            return
        slot, col, values = event
        assert col == slot.columns
        for row, value in enumerate(values):
            bank, address = slot.cell(row, col)
            assert bank not in ports and self.input_banks[bank][address] is None
            self.input_banks[bank][address] = slot.sequence, value
            ports.add(bank)
        slot.columns += 1
        self.stats["quant_halfwords"] += len(values)
        self.marks["last_emit"] = self.cycle
        if slot.columns == 16:
            page = self.pages[slot.tile % 2]
            assert page is not None and page.tile == slot.tile
            page.emitted += 1

    def mac(self):
        weight_ports = set()
        for col in range(16):
            read_age = 1 + 2 * col
            read = self.tokens[(self.cycle - read_age) % 64] if self.cycle >= read_age else None
            execute = self.tokens[(self.cycle - read_age - 1) % 64] if self.cycle > read_age else None
            if execute:
                self.marks.setdefault("first_mac", self.cycle)
                slot, k = execute.slot, execute.inner
                page = self.pages[slot.tile % 2]
                assert page is not None and page.tile == slot.tile
                tile, inner, w = self.weight_q[col]
                assert (tile, inner) == (slot.tile, k)
                context = self.acc[slot.group % 2]
                results = []
                for row, x in enumerate(execute.values):
                    prior = context[row][col]
                    if k == 0:
                        assert prior is None
                        value = page.bias[col] + x * w
                    else:
                        assert prior[:2] == (slot.sequence, k)
                        value = prior[2] + x * w
                    value = baseline.q16.signed(value, 36)
                    self.mac_operations += 1
                    if k == 63:
                        results.append(baseline.q16.rne(value, page.shift[col]))
                        context[row][col] = None
                    else:
                        context[row][col] = slot.sequence, k + 1, value
                if results:
                    when = self.cycle + 2
                    assert when not in self.quant
                    self.quant[when] = slot, col, tuple(results)
            if read and read.weight_read:
                address = 64 * (read.slot.tile % 2) + read.inner
                value = self.weight_banks[col][address]
                assert value[:2] == (read.slot.tile, read.inner)
                self.weight_q[col] = value
                weight_ports.add(col)
        self.stats["weight_macro_reads"] += len(weight_ports)
        return weight_ports

    def commit_weight(self, ports):
        if self.weight_pack is None or not self.incoming:
            return False
        addr, data = self.incoming[0]
        saved_addr, saved_data = self.weight_pack
        assert addr == saved_addr + 1
        tile, offset = divmod(saved_addr - PARAMETER_BASE, PACKET_WORDS)
        k, pair = divmod(offset - 20, 8)
        banks = range(2 * pair, 2 * pair + 4)
        if any(bank in ports for bank in banks):
            self.stats["weight_write_wait"] += 1
            return False
        page = self.pages[tile % 2]
        assert page.tile == tile and page.written == offset
        for bank, value in zip(banks, halves(saved_data) + halves(data)):
            self.weight_banks[bank][64 * (tile % 2) + k] = tile, k, value
        self.weight_pack = None
        self.incoming.popleft()
        page.written += 2
        self.stats["weight_write64"] += 1
        if page.written == PACKET_WORDS:
            self.page_history.append([tile, self.cycle])
        return True

    def load_private(self, ports, weight_ports):
        if not self.incoming:
            return
        if self.weight_pack is not None:
            self.commit_weight(weight_ports)
            return
        addr, data = self.incoming[0]
        if addr < INPUT_WORDS:
            assert addr == self.input_written
            rows = self.identities[2*addr:2*addr+2]
            cells = [input_location(row, k) for row, k in rows]
            assert cells[0][0] != cells[1][0]
            if any(bank in ports for bank, _ in cells):
                self.stats["input_write_wait"] += 1
                return
            for (row, _), (bank, offset), value in zip(rows, cells, halves(data)):
                assert self.input_banks[bank][offset] is None
                self.input_banks[bank][offset] = row, value
                ports.add(bank)
            self.input_written += 1
        else:
            tile, offset = divmod(addr - PARAMETER_BASE, PACKET_WORDS)
            page = self.pages[tile % 2]
            assert page.tile == tile and page.written == offset
            if offset < 16:
                page.bias[offset] = baseline.q16.signed(data, 32)
                page.written += 1
            elif offset < 20:
                col = 4 * (offset - 16)
                page.shift[col:col+4] = [baseline.q16.signed((data >> (8*i)) & 255, 8) for i in range(4)]
                page.written += 1
            else:
                self.weight_pack = addr, data
        self.incoming.popleft()

    def retire_pages(self):
        while self.oldest < TILES:
            page = self.pages[self.oldest % 2]
            if page is None or page.tile != self.oldest or page.emitted != 25:
                break
            assert page.next_unit == CONTEXTS and page.written == PACKET_WORDS
            self.pages[self.oldest % 2] = None
            self.oldest += 1

    def next_source(self):
        if self.cycle < self.kickoff or self.read_index == DATA_WORDS or len(self.incoming) >= 2:
            return None
        addr = self.order[self.read_index]
        if addr not in self.shared:
            self.stats["dma_wait_host_word"] += 1
            return None
        if addr >= PARAMETER_BASE:
            tile, offset = divmod(addr - PARAMETER_BASE, PACKET_WORDS)
            page = self.pages[tile % 2]
            if (page is not None and page.tile != tile) or tile > self.oldest + 1:
                self.stats["dma_wait_page_release"] += 1
                return None
            assert page is not None or offset == 0
        return addr

    def prefetch_output(self, ports):
        # Two packed words can be reserved in the private read/hold path.
        # The shared controller has its own one-transaction response owner.
        if len(self.out_held) == 2:
            return
        available = []
        for ring in self.slots:
            head = next((slot for slot in ring if slot.reads < slot.words), None)
            if head is not None and head.columns == 16:
                available.append(head)
        for slot in sorted(available, key=lambda s: (s.side not in self.blocked_sides, s.sequence)):
            row, pair = divmod(slot.reads, 8)
            c = 2 * pair
            cells = [slot.cell(row, c + half) for half in range(2)]
            if any(bank in ports for bank, _ in cells):
                self.stats["result_read_bank_conflict"] += 1
                continue
            values = []
            for bank, address in cells:
                sequence, value = self.input_banks[bank][address]
                assert sequence == slot.sequence
                values.append(value)
                ports.add(bank)
            index = (4 * slot.group + row) * 256 + 16 * slot.tile + c
            assert tuple(self.golden[index:index+2]) == tuple(values), (self.case, self.cycle, index, values)
            self.out_pending = slot, index, packed(*values)
            slot.reads += 1
            self.stats["result_macro_reads"] += 2
            return

    def write_shared(self, packet):
        slot, index, data = packet
        addr = RESULT_BASE + index // 2
        assert addr not in self.out_memory and addr not in self.shared
        self.out_memory[addr] = data
        slot.committed += 1
        self.output_written += 1
        self.marks.setdefault("first_physical_commit", self.cycle)
        self.marks["final_physical_commit"] = self.cycle
        if slot.committed == slot.words:
            assert slot.reads == slot.words
            assert self.slots[slot.side].popleft() is slot
            for row in range(slot.words // 8):
                for col in range(16):
                    bank, address = slot.cell(row, col)
                    assert self.input_banks[bank][address][0] == slot.sequence
                    self.input_banks[bank][address] = None

    def transfer(self, ports):
        previous = self.bus_pending
        self.bus_pending = None
        if previous:
            kind, address, word = previous
            if kind == "read":
                self.incoming.append((address, word))
                assert len(self.incoming) <= 2
            elif self.output_written == RESULT_COUNT // 2:
                self.marks["final_ack"] = self.cycle

        source = self.next_source()
        if self.blocked_sides:
            self.preempt = True
        elif self.preempt and not any(len(ring) == limit for ring, limit in zip(self.slots, RING_LIMIT)):
            self.preempt = False
        next_tile = ((self.order[self.read_index] - PARAMETER_BASE) // PACKET_WORDS
                     if self.read_index < DATA_WORDS else TILES)
        # Hold the source direction across temporary ingress stalls. A tile
        # waiting for an old page is a true window for result retirement.
        output_window = self.preempt or self.read_index == DATA_WORDS or next_tile > self.oldest + 1
        choose_out = bool(self.out_held and output_window)
        direction = "write" if choose_out else "read" if source is not None and not self.preempt else None
        if direction and previous and previous[0] != direction:
            self.stats["dma_direction_turnaround"] += 1
            direction = None
        cpu_busy = self.cycle in self.cpu_reserved
        assert not cpu_busy or not direction
        setup = self.cpu_setup.get(self.cycle)
        if setup:
            address = (setup["address"] - baseline.t.BASE) // 4
            if setup["read"]:
                assert self.shared[address] == 1
            else:
                self.shared[address] = setup["data"]
        busy_bank = None
        if direction == "read":
            addr = source
            busy_bank = physical_bank(addr)
            self.bus_pending = direction, addr, self.shared[addr]
            self.read_index += 1
            if addr >= PARAMETER_BASE:
                tile, offset = divmod(addr - PARAMETER_BASE, PACKET_WORDS)
                if offset == 0:
                    assert self.pages[tile % 2] is None
                    self.pages[tile % 2] = Page(tile)
        elif direction == "write":
            packet = self.out_held.popleft()
            addr = RESULT_BASE + packet[1] // 2
            busy_bank = physical_bank(addr)
            self.write_shared(packet)
            self.bus_pending = direction, addr, packet[2]

        if self.host_index < len(self.host_order) and self.cycle >= self.host_start:
            addr, data = self.host_order[self.host_index]
            allowed = (direction is None and previous is None and not cpu_busy or
                       direction == "read" and physical_bank(addr) != busy_bank)
            if allowed:
                assert addr not in self.out_memory
                if addr in self.source:
                    assert addr not in self.shared
                    self.stats["host_payload_commits"] += 1
                    self.marks.setdefault("first_host_physical_commit", self.cycle)
                else:
                    self.stats["host_setup_commits"] += 1
                self.shared[addr] = data
                self.host_index += 1
                self.stats["host_dual"] += direction == "read"
            else:
                self.stats["host_wait_" + ("same_bank" if direction == "read" else "owner")] += 1

        if self.out_pending is not None:
            self.out_held.append(self.out_pending)
            self.out_pending = None
        self.prefetch_output(ports)
        self.read_peak = max(self.read_peak, len(self.incoming) + int(direction == "read"))
        self.output_credit_peak = max(self.output_credit_peak,
                                      len(self.out_held) + int(self.out_pending is not None))
        assert self.read_peak <= 2 and self.output_credit_peak <= 2
        self.stats["shared_" + (direction or "no_dma")] += 1

    def run(self):
        last = None
        stagnant = 0
        while "final_ack" not in self.marks:
            self.tokens[self.cycle % 64] = None
            ports = set()
            self.finish_output_column(ports)
            self.retire_pages()
            self.issue(ports)
            weight_ports = self.mac()
            self.load_private(ports, weight_ports)
            self.transfer(ports)
            progress = (self.host_index, self.read_index, self.input_written, self.issue_count,
                        self.output_written, self.stats["quant_halfwords"], self.stats["weight_write64"])
            if (self.cycle >= self.kickoff and self.bus_pending is None and
                    self.out_pending is None and self.cycle > self.max_last_issue + 35):
                stagnant = stagnant + 1 if last == progress else 0
                if stagnant == 2:
                    return self.summary(False)
            else:
                stagnant = 0
            last = progress
            self.cycle += 1
        assert self.host_index == len(self.host_order) and self.read_index == DATA_WORDS
        assert self.input_written == INPUT_WORDS and self.issue_count == 25600
        assert self.stats["host_payload_commits"] == DATA_WORDS and self.stats["host_setup_commits"] == 10
        assert self.mac_operations == RESULT_COUNT * 64
        assert self.stats["quant_halfwords"] == self.stats["result_macro_reads"] == RESULT_COUNT
        assert self.stats["weight_write64"] == 4096
        assert not any(self.slots) and self.oldest == TILES
        for index in range(0, RESULT_COUNT, 2):
            assert halves(self.out_memory[RESULT_BASE + index//2]) == tuple(self.golden[index:index+2])
        return self.summary(True)

    def summary(self, complete):
        return dict(case=self.case, complete=complete, cold_cycles=self.marks.get("final_physical_commit", -1) + 1,
                    **self.marks, stopped_at=self.cycle, host_words=self.host_index,
                    dma_reads=self.read_index, dma_writes=self.output_written,
                    mac_operations=self.mac_operations, compute_issues=self.issue_count,
                    ring_peak=self.ring_peak, read_credit_peak=self.read_peak,
                    output_credit_peak=self.output_credit_peak, early_tile_units=self.early_switches,
                    input_written=self.input_written, oldest_page=self.oldest,
                    remaining_rings=[[(s.tile, s.group, s.columns, s.reads, s.committed) for s in ring]
                                     for ring in self.slots],
                    page_ready=self.page_history, unit_launches=self.unit_history, counters=dict(self.stats))


def save(name, payload):
    (REPORT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def candidate(case, controls, kickoff, host_start, cpu_setup):
    return StreamingTask(case, controls, kickoff, host_start, cpu_setup).run()


def baseline_case(case, program, controls, host_start):
    return baseline.simulate("M0", case, program, controls, host_start)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, choices=range(1, 13))
    args = parser.parse_args()
    program, controls, host_start, events = baseline.observe()
    # Preserve the measured cold-start CPU prologue budget. After this modeled START,
    # the accelerator, rather than firmware descriptor polling, schedules the transfers.
    kickoff = next(command["accept"] for command in program if command["bus"] == "cpu"
                   and command["address"] == 0x48 and not command["read"])
    cpu_setup = [command for command in program
                 if command["bus"] == "shared_cpu" and command["accept"] < kickoff]
    host_controls = controls + [(baseline.t.READY_WORD, 1)]
    REPORT.mkdir(parents=True, exist_ok=True)
    if args.case:
        row = candidate(args.case - 1, host_controls, kickoff, host_start, cpu_setup)
        print(row["complete"], row["cold_cycles"], row["stopped_at"], row["counters"], flush=True)
        save("case-%02d.json" % args.case, row)
        return
    first = baseline.simulate("M0", 0, program, controls, host_start, events)
    assert not first["differences"], first["differences"][:5]
    anchors = {key: first[key] for key in baseline.ANCHORS}
    assert anchors == baseline.ANCHORS
    print("M0 case 1 native comparison:", anchors, flush=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        base_jobs = [pool.submit(baseline_case, case, program, controls, host_start)
                     for case in range(1, 12)]
        candidate_jobs = [pool.submit(candidate, case, host_controls, kickoff, host_start, cpu_setup)
                          for case in range(12)]
        base = [first] + [job.result() for job in base_jobs]
        rows = [job.result() for job in candidate_jobs]
    for row in rows:
        print("TWOPAGE", row["case"], row["complete"], row["cold_cycles"], flush=True)
    base_cycles = sum(row["cold_cycles"] for row in base)
    assert base_cycles == 399144 and all(row["cold_cycles"] == 33262 for row in base)
    cycles = sum(row["cold_cycles"] for row in rows) if all(row["complete"] for row in rows) else None
    save("baseline.json", dict(cold_cycles_total=base_cycles, case1_anchors=anchors, rows=base))
    save("screen.json", dict(case1_anchors=anchors, baseline_cycles_total=base_cycles,
                             kickoff=kickoff, host_start=host_start, cpu_setup=cpu_setup,
                             target_cycles=CYCLE_TARGET, cold_cycles_total=cycles,
                             throughput=None if cycles is None else 12 * CLOCK / cycles,
                             passes_model=cycles is not None and cycles <= CYCLE_TARGET, rows=rows))


if __name__ == "__main__":
    main()


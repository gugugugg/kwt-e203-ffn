"""Numerical screening of the two-page core on a single physical ICB target."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import csv
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sysbus32_twopage', ROOT / 'scripts/trb_twopage/screen.py')
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

REPORT = ROOT / 'reports/optimization/ffn_sysbus32_3k'
TARGET = 600000


class SingleBusTask(base.StreamingTask):
    def __init__(self, case, controls, cpu_commands, kickoff):
        super().__init__(case, controls, kickoff, 0, [])
        self.cpu_commands = deque(cpu_commands)
        self.slots = [deque()]
        self.free_slots = deque(range(32))
        self.result_banks = [[None] * 128 for _ in range(16)]
        self.result_ports = set()
        self.commands = deque()
        self.responses = deque()
        self.source_in_flight = 0
        self.final_commit_response = False

    def reserve(self, page, pair):
        reserved = []
        for group in range(2 * pair, min(2 * pair + 2, 25)):
            slot = base.Slot(0, self.free_slots.popleft(), page.tile, group, self.slot_sequence)
            self.slot_sequence += 1
            self.slots[0].append(slot)
            reserved.append(slot)
        self.ring_peak[0] = max(self.ring_peak[0], len(self.slots[0]))
        return tuple(reserved)

    def start_unit(self):
        if self.cycle < self.kickoff:
            return 'prelude'
        reasons = []
        for page in sorted((p for p in self.pages if p is not None), key=lambda p: p.tile):
            pair = page.next_unit
            if pair == base.CONTEXTS:
                continue
            if page.written < base.PACKET_WORDS:
                reasons.append('weight_page')
            elif self.input_written < min((pair + 1) * 256, base.INPUT_WORDS):
                reasons.append('input_prefix')
            elif len(self.free_slots) < (1 if pair == 12 else 2):
                reasons.append('result_slots')
            elif pair != 12 and self.cycle % 2:
                reasons.append('pair_phase')
            else:
                page.next_unit += 1
                self.unit = base.Unit(page, pair, self.reserve(page, pair))
                self.unit_history.append([self.cycle, page.tile, pair])
                self.early_switches += page.tile > self.oldest
                return None
        return reasons[0] if reasons else 'weight_page_or_pipeline'

    def issue(self, ports):
        if self.unit is None:
            reason = self.start_unit()
            if reason:
                self.stats['issue_wait_' + reason] += 1
                return
        unit = self.unit
        paired = unit.pair != 12
        slot = unit.slots[unit.index % 2] if paired else unit.slots[0]
        inner = unit.index // 2 if paired else unit.index
        values = []
        for row in range(4 * slot.group, min(4 * slot.group + 4, 99)):
            bank, offset = base.input_location(row, inner)
            identity, value = self.input_banks[bank][offset]
            assert row == identity and bank not in ports
            values.append(value)
            ports.add(bank)
        # Each column reuses the previous weight on the second context.
        self.tokens[self.cycle % 64] = base.Token(slot, inner, tuple(values), not paired or unit.index % 2 == 0)
        self.max_last_issue = self.cycle
        self.issue_count += 1
        self.stats['input_macro_reads'] += len(values)
        unit.index += 1
        if unit.index == unit.length:
            self.unit = None

    @staticmethod
    def result_cell(slot, row, col):
        return 4 * row + col % 4, 4 * slot.index + col // 4

    def finish_output_column(self, ports):
        self.result_ports.clear()
        event = self.quant.pop(self.cycle, None)
        if event is None:
            return
        slot, col, values = event
        assert col == slot.columns
        for row, value in enumerate(values):
            bank, address = self.result_cell(slot, row, col)
            assert bank not in self.result_ports and self.result_banks[bank][address] is None
            self.result_banks[bank][address] = slot.sequence, value
            self.result_ports.add(bank)
        slot.columns += 1
        self.stats['quant_halfwords'] += len(values)
        self.marks['last_emit'] = self.cycle
        if slot.columns == 16:
            page = self.pages[slot.tile % 2]
            assert page is not None and page.tile == slot.tile
            page.emitted += 1

    def prefetch_output(self, ports):
        if len(self.out_held) == 2:
            return
        slot = next((item for item in self.slots[0] if item.reads < item.words), None)
        if slot is None or slot.columns != 16:
            return
        row, pair = divmod(slot.reads, 8)
        col = 2 * pair
        cells = [self.result_cell(slot, row, col + half) for half in range(2)]
        if any(bank in self.result_ports for bank, _ in cells):
            self.stats['result_read_bank_conflict'] += 1
            return
        values = []
        for bank, address in cells:
            sequence, value = self.result_banks[bank][address]
            assert sequence == slot.sequence
            values.append(value)
            self.result_ports.add(bank)
        index = (4 * slot.group + row) * 256 + 16 * slot.tile + col
        assert tuple(values) == tuple(self.golden[index:index+2])
        self.out_pending = slot, index, base.packed(*values)
        slot.reads += 1
        self.stats['result_macro_reads'] += 2

    def write_shared(self, packet):
        slot, index, data = packet
        address = base.RESULT_BASE + index // 2
        assert address not in self.out_memory and address not in self.shared
        self.out_memory[address] = data
        self.output_written += 1
        slot.committed += 1
        self.marks.setdefault('first_physical_commit', self.cycle)
        self.marks['final_physical_commit'] = self.cycle
        if slot.committed == slot.words:
            assert slot.reads == slot.words and self.slots[0].popleft() is slot
            for row in range(slot.words // 8):
                for col in range(16):
                    bank, address = self.result_cell(slot, row, col)
                    assert self.result_banks[bank][address][0] == slot.sequence
                    self.result_banks[bank][address] = None
            self.free_slots.append(slot.index)

    def transfer(self, ports):
        command_room = len(self.commands) < 2
        response_room = len(self.responses) < 2
        owner_credit = (len(self.commands) + len(self.responses) + int(self.bus_pending is not None)) < 4
        if self.responses:
            kind, address, word = self.responses.popleft()
            if kind == 'source':
                self.source_in_flight -= 1
                self.incoming.append((address, word))
                self.stats['read_ack'] += 1
            elif kind == 'result':
                self.stats['write_ack'] += 1
                if self.stats['write_ack'] == base.RESULT_COUNT // 2:
                    self.marks['final_ack'] = self.cycle
        if self.final_commit_response:
            return
        if self.bus_pending is not None:
            self.stats['bus_retire_only'] += 1
            if response_room:
                self.responses.append(self.bus_pending)
                self.bus_pending = None
        elif self.commands and response_room:
            self.commit_request(*self.commands.popleft())
        else:
            self.stats['bus_idle'] += 1
        if command_room and owner_credit and not self.final_commit_response:
            self.queue_request()
        if self.out_pending is not None:
            self.out_held.append(self.out_pending)
            self.out_pending = None
        self.prefetch_output(ports)
        self.read_peak = max(self.read_peak, len(self.incoming) + self.source_in_flight)
        self.output_credit_peak = max(self.output_credit_peak, len(self.out_held) + int(self.out_pending is not None))
        assert self.read_peak <= 2 and self.output_credit_peak <= 2

    def queue_request(self):
        source = self.next_source() if len(self.incoming) + self.source_in_flight < 2 else None
        occupancy = len(self.slots[0])
        if occupancy >= 24:
            self.preempt = True
        elif occupancy <= 16:
            self.preempt = False
        if self.cpu_commands and self.cpu_commands[0]['accept'] <= self.cycle:
            cmd = self.cpu_commands[0]
            address = (cmd['address'] - base.baseline.t.BASE) // 4
            if not cmd['read'] or address in self.shared:
                self.cpu_commands.popleft()
                self.commands.append(('cpu_read' if cmd['read'] else 'cpu_write', address, cmd['data']))
                return
        if self.out_held and (self.preempt or source is None):
            self.commands.append(('result', None, self.out_held.popleft()))
        elif source is not None:
            self.commands.append(('source', source, None))
            self.source_in_flight += 1
            self.read_index += 1
            if source >= base.PARAMETER_BASE:
                tile, offset = divmod(source - base.PARAMETER_BASE, base.PACKET_WORDS)
                if offset == 0:
                    assert self.pages[tile % 2] is None
                    self.pages[tile % 2] = base.Page(tile)
        elif self.host_index < len(self.host_order):
            address, data = self.host_order[self.host_index]
            self.commands.append(('host', address, data))
            self.host_index += 1

    def commit_request(self, kind, address, data):
        if kind == 'host':
            assert address not in self.out_memory
            self.shared[address] = data
            self.stats['bus_host'] += 1
            self.stats['host_payload_commits' if address in self.source else 'host_setup_commits'] += 1
        elif kind == 'result':
            self.write_shared(data)
            self.stats['bus_result'] += 1
            self.final_commit_response = self.output_written == base.RESULT_COUNT // 2
            if self.final_commit_response:
                self.marks['final_target_ack'] = self.cycle
        elif kind == 'source':
            self.bus_pending = kind, address, self.shared[address]
            self.stats['bus_source'] += 1
            return
        else:
            self.stats['bus_cpu'] += 1
            if kind == 'cpu_read':
                self.bus_pending = kind, address, self.shared[address]
                return
            self.shared[address] = data
        self.responses.append((kind, address, data))

    def run(self):
        # Bus FIFO moves also constitute progress during the initial fill/drain.
        while 'final_ack' not in self.marks and self.cycle < 110000:
            self.tokens[self.cycle % 64] = None
            ports = set()
            self.finish_output_column(ports)
            self.retire_pages()
            self.issue(ports)
            self.load_private(ports, self.mac())
            self.transfer(ports)
            self.cycle += 1
        if 'final_ack' not in self.marks:
            return self.summary(False)
        assert self.host_index == len(self.host_order) and self.read_index == base.DATA_WORDS
        assert self.input_written == base.INPUT_WORDS and self.issue_count == 25600
        assert self.stats['host_payload_commits'] == base.DATA_WORDS and self.stats['host_setup_commits'] == 10
        assert self.mac_operations == base.RESULT_COUNT * 64
        assert self.stats['quant_halfwords'] == self.stats['result_macro_reads'] == base.RESULT_COUNT
        assert self.stats['weight_write64'] == 4096
        assert not self.slots[0] and self.oldest == base.TILES
        for index in range(0, base.RESULT_COUNT, 2):
            assert base.halves(self.out_memory[base.RESULT_BASE + index//2]) == tuple(self.golden[index:index+2])
        return self.summary(True)


def candidate(case, controls, cpu, kickoff):
    row = SingleBusTask(case, controls, cpu, kickoff).run()
    if row['complete']:
        counts = row['counters']
        assert counts['read_ack'] == base.DATA_WORDS and counts['write_ack'] == base.RESULT_COUNT // 2
        assert (counts['bus_host'] + counts['bus_source'] + counts['bus_result'] +
                counts['bus_cpu'] + counts['bus_idle'] + counts['bus_retire_only']) == row['cold_cycles']
    return row


def calibration():
    observed = REPORT / ('received/baseline-observation/native-evidence/reports/optimization/'
                         'ffn_sysbus32_3k/baseline-observation/events.csv')
    native = json.loads((REPORT.parent / 'ffn_trb_sysbus32/cpu-result.json').read_text(encoding='utf-8'))
    case = native['cases'][0]
    upstream, target, cpu = [], [], []
    kickoff = None
    with observed.open(newline='', encoding='utf-8') as stream:
        for expected_edge, fields in enumerate(csv.reader(stream)):
            edge = int(fields[0])
            assert edge == expected_edge
            if fields[17] == fields[18] == '1':
                upstream.append((edge, fields[16], fields[19]))
            if fields[21] == fields[22] == '1':
                target.append((edge, fields[20], fields[30]))
            if fields[1] == fields[2] == '1':
                cpu.append(dict(accept=edge, address=int(fields[5], 16), read=fields[3] == '1', data=0))
            if kickoff is None and fields[11] == fields[14] == '1':
                kickoff = edge
    assert expected_edge + 1 == case['cycles']
    # The first target word is the observed boot mailbox write already in flight
    # at cycle 0. All remaining arrivals use the measured upstream accept edges.
    predicted = [(1, 'a007fffc', '0')]
    next_edge = 3
    for arrival, address, read in upstream:
        edge = max(next_edge, arrival + 1)
        predicted.append((edge, address, read))
        next_edge = edge + 2
    assert predicted == target and predicted[-1][0] == case['last_commit']
    result = dict(cold_cycles=predicted[-1][0] + 1, final_physical_commit=predicted[-1][0],
                  native_last_ack=case['last_ack'], exact_physical_requests=len(predicted),
                  scope='bus replay from upstream accepts, including pre-window in-flight boot write',
                  cpu_requests=cpu, first_native_dma_accept=kickoff)
    (REPORT / 'baseline-calibration.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    # The task-request notification contains the current sequence number.
    for cmd in cpu:
        if not cmd['read']:
            cmd['data'] = 1
    return result, cpu, kickoff


def main():
    bus = json.loads((REPORT / 'bus-screen.json').read_text(encoding='utf-8'))
    phases = bus['measurements']['commit_ack']
    assert phases['writes']['max_gap'] == 1 and phases['reads']['max_gap'] == 2
    _, controls, _, _ = base.baseline.observe()
    measured, cpu, kickoff = calibration()
    controls = controls + [(base.baseline.t.READY_WORD, 1)]
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(candidate, i, controls, cpu, kickoff) for i in range(12)]
        rows = [job.result() for job in jobs]
    complete = all(row['complete'] for row in rows)
    cycles = sum(row['cold_cycles'] for row in rows) if complete else None
    result = dict(target_cycles=TARGET, cold_cycles_total=cycles, passes_cycle_screen=complete and cycles <= TARGET,
                  throughput=1800000000 / cycles if complete else None,
                  baseline_physical_requests_matched=measured['exact_physical_requests'], complete_soc_rtl_allowed=False,
                  timing_scope='measured physical ICB service, two command and response entries, four owner credits',
                  cpu_scope='current native CPU startup request release edges, subsequent transfers modeled in hardware',
                  kickoff=kickoff, rows=rows)
    (REPORT / 'candidate-model.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('SYSBUS32_MODEL', cycles, result['throughput'], result['passes_cycle_screen'], flush=True)


if __name__ == '__main__':
    main()

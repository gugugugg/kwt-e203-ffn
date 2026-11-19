"""Causal result retirement screen using the published M3 transport and arithmetic."""
from concurrent.futures import ProcessPoolExecutor
import inspect
import json
from pathlib import Path
import sys
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_m3_retire'
OBS = REPORT / 'received/observation/native-evidence' / REPORT.relative_to(ROOT) / 'observation'
sys.path.insert(0, str(ROOT / 'scripts/r3o_stream'))
import screen as m3
from native_model import SharedMemory
from transport import Wrapper

MODES = ('M0', 'R4', 'R4+F2')
PACES = ('response_relative', 'fixed_cpu')
ANCHORS = dict(first_mac=21159, last_row0_emit=75074, final_physical_commit=75600,
               final_ack=75601, cold_cycles=75601)


class RetireQueue(m3.r3o.ResultQueue):
    def __init__(self, direct):
        self.direct = direct

    def reset(self):
        super().reset()
        self.bypassed = self.consecutive_paired_reads = self.paired_reads = 0
        self.previous_pair = False
        self.return_peak = self.reservation_peak = 0

    def comb(self, item, push, push_row, single, paired):
        pop = 2 if paired and len(self.held) >= 2 else int(bool(single and self.held))
        next_item = item + len(self.held) + len(self.pending)
        next_row = (next_item // 256) % 3
        space = 4 - len(self.held) - len(self.pending) + pop
        readable = space > 0 and next_item < 25344
        available = [len(row) for row in self.rows]
        row0_count = available[0] + (len(self.pending) if self.pending_row == 0 else 0)
        bypass = 0
        if self.direct and readable and next_row == 0 and row0_count == 0 and not self.pending:
            bypass = min(2, space, len(self.fifo), 256 - next_item % 256)
        read0 = readable and next_row == 0 and available[0] > 0
        drain = bool(self.fifo and row0_count < 128 and not read0 and not bypass)
        room = (len(self.fifo) + 2 <= 16 + int(drain) + bypass if push_row == 0
                else available[push_row] + 2 <= 256)
        accept = push and room
        read = 0
        if readable and available[next_row] and not (accept and push_row != 0 and push_row == next_row):
            read = 2 if next_row and space >= 2 and available[next_row] >= 2 and next_item % 256 != 255 else 1
        return dict(pop_count=pop, read=read, next_row=next_row, drain=drain, ready=room,
                    accept=accept, push_row=push_row, blocked=push and not room, bypass=bypass)

    def tick(self, control, pair, restart=False):
        if restart:
            return super().tick(control, pair, restart)
        bypass = control['bypass']
        if bypass and (control['read'] or control['drain'] or self.pending):
            raise RuntimeError('FIFO direct transfer conflicts with a stash access or return')
        direct_words = [self.fifo.popleft() for _ in range(bypass)]
        result = super().tick(control, pair)
        self.held.extend(direct_words)
        reserved = len(self.held) + len(self.pending)
        if reserved > 4:
            raise RuntimeError('Result return reservation exceeded four halfwords')
        self.bypassed += bypass
        pair_read = control['read'] == 2
        self.paired_reads += int(pair_read)
        self.consecutive_paired_reads += int(pair_read and self.previous_pair)
        self.previous_pair = pair_read
        self.return_peak = max(self.return_peak, len(self.held))
        self.reservation_peak = max(self.reservation_peak, reserved)
        return result


def widened(function, edits):
    source = dedent(inspect.getsource(function))
    for old, new in edits:
        if old not in source:
            raise RuntimeError('Frozen model changed: ' + old)
        source = source.replace(old, new)
    namespace = dict(function.__globals__)
    exec(compile(source, str(Path(__file__)), 'exec'), namespace)
    return namespace[function.__name__]


# The downstream DMA still reads two words at a time. It can now do so when
# the registered result queue contains more than two words.
Wrapper.comb = widened(Wrapper.comb, [('h == 2', 'h >= 2')])
m3.sr.WriteMemory.comb = widened(SharedMemory.comb, [
    ("self.owner_read and grant and b['valid'] and b['read']",
     "grant and b['valid'] and self.owner_read == b['read']"),
    ('len(w.core.queue.held) == 2', 'len(w.core.queue.held) >= 2'),
])


class MeasuredWrapper(m3.StreamWrapper):
    def __init__(self, case, mode):
        super().__init__('M3', case)
        self.write_handoffs = self.consecutive_paired_reads = self.paired_reads = 0
        self.previous_pair = False
        self.return_peak = self.reservation_peak = 0
        if mode != 'M0':
            self.core.queue = RetireQueue(mode == 'R4+F2')
            self.core.queue.reset()

    def tick(self, cpu, c, cycle):
        memory = c['memory']
        self.write_handoffs += int(bool(memory['fire'] and memory['grant']
                                       and not memory['selected']['read']
                                       and memory['valid'] and memory['rsp_ready']))
        result = super().tick(cpu, c, cycle)
        queue = self.core.queue
        pair_read = len(queue.pending) == 2
        self.paired_reads += int(pair_read)
        self.consecutive_paired_reads += int(pair_read and self.previous_pair)
        self.previous_pair = pair_read
        self.return_peak = max(self.return_peak, len(queue.held))
        self.reservation_peak = max(self.reservation_peak, len(queue.held) + len(queue.pending))
        return result


def simulate(mode, pacing, case, prefix, commands, prior, compare=None):
    wrapper = MeasuredWrapper(case, mode)
    run = widened(m3.simulate, [('wrapper = StreamWrapper(mode, case)', 'wrapper = retirement_wrapper')])
    run.__globals__['retirement_wrapper'] = wrapper
    row = run('M3', pacing, case, prefix, commands, prior, compare)
    queue = wrapper.core.queue
    row.update(mode=mode, stalled_by_row=queue.blocked,
               paired_reads=wrapper.paired_reads, consecutive_paired_reads=wrapper.consecutive_paired_reads,
               dma_write_handoffs=wrapper.write_handoffs, fifo_direct_words=getattr(queue, 'bypassed', 0),
               return_peak=wrapper.return_peak, reservation_peak=wrapper.reservation_peak)
    return row


def save(name, data):
    (REPORT / name).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main():
    m3.OBS = OBS
    prefix, commands, prior = m3.read_program()
    rows = {}
    for row in m3.trace_rows(OBS / 'events.csv'):
        row.update({key.replace('.', '_'): val for key, val in row.items() if '.' in key})
        rows[row['cycle']] = row
    base = simulate('M0', PACES[0], 0, prefix, commands, prior, rows)
    actual = {key: base[key] for key in ANCHORS}
    passed = actual == ANCHORS and not base['divergence']
    save('calibration.json', dict(passed=passed, expected=ANCHORS, actual=actual, model=base))
    print('M3_CALIBRATION', passed, actual, base['divergence'][:2], flush=True)
    if not passed:
        raise RuntimeError('Resolve native calibration before choosing hardware')
    runs = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(simulate, mode, pacing, case, prefix, commands, prior)
                   for pacing in PACES for mode in MODES for case in range(12)]
        for work in pending:
            row = work.result()
            runs.append(row)
            print('RETIRE_MODEL', row['mode'], row['pacing'], row['case'], row['cold_cycles'],
                  row['stalled_by_row'], row['consecutive_paired_reads'], row['dma_write_handoffs'],
                  row['fifo_direct_words'], flush=True)
    totals = {pacing: {mode: sum(row['cold_cycles'] for row in runs
                                if row['pacing'] == pacing and row['mode'] == mode)
                       for mode in MODES} for pacing in PACES}
    primary = totals[PACES[0]]
    chosen = min(MODES[1:], key=primary.get)
    selected = chosen if primary[chosen] < min(primary['M0'], 907212) else None
    save('model-selection.json', dict(passed=True, selected=selected, cycles_total=totals,
         throughput={pacing: {mode: 1800000000 / cycles for mode, cycles in sums.items()}
                     for pacing, sums in totals.items()},
         measured_hardware=False, internal_ready_replayed=False, runs=runs))
    print('RETIRE_SELECTION', selected, totals, flush=True)


if __name__ == '__main__':
    main()

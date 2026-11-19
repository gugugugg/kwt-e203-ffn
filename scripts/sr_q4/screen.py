"""SR Q4 model with independent row acceptance on the original storage ports."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sr_q4'
sys.path[:0] = [str(ROOT / 'scripts' / name) for name in
                ('c16_efficiency', 'column_parallel', 'taskflow_study')]
from models import ControlCore, WriteWrapper, parent_timing, run
from model import OutputQueue, rne
from model_validate import normal

ANCHORS = dict(cold_cycles=98783, first_mac=29895, last_emit=98754,
               final_physical_commit=98782, final_ack=98784)


class DualQueue(OutputQueue):
    def comb_pair(self, item, emit, row0_done, two_rows, ready, pair_ready):
        first = super().comb(item, emit and not row0_done, False, ready, pair_ready)
        if emit and two_rows and (row0_done or first['row0_push']):
            second = super().comb(item, True, True, ready, pair_ready)
            second.update(row0_push=first['row0_push'], room0=first['ready'],
                          row1_attempt=True)
            return second
        first.update(room0=first['ready'], row1_attempt=False)
        return first

    def tick(self, c, pair, restart=False):
        if 'pairs' not in c:
            return super().tick(c, pair, restart)
        # Base tick handles old held/pending, FIFO drain and row0. A row1 write
        # has already displaced any new row1 read in the combinational decision.
        row0, row1 = c['pairs']
        popped = super().tick(dict(c, row1_push=False), row0, restart)
        if c['row1_push']:
            if c['read1'] or self.row1_write & 1:
                raise RuntimeError('Invalid physical row1 bank write')
            for offset, token in enumerate(row1):
                self.row1[(self.row1_write + offset) & 255] = token
            self.row1_write = (self.row1_write + 2) & 255
            self.row1_count += 2
            self.peak['row1'] = max(self.peak['row1'], self.row1_count)
            self.peak['total'] = max(self.peak['total'], self.fifo_count +
                                     self.row0_count + self.row1_count + len(self.held))
        if not (0 <= self.fifo_count <= 16 and 0 <= self.row0_count <= 128
                and 0 <= self.row1_count <= 256 and len(self.held) + len(self.pending) <= 2):
            raise RuntimeError('Q4 exceeded a physical capacity')
        return popped


class Q4Core(ControlCore):
    instance = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = DualQueue()
        self.completed = []
        Q4Core.instance = self

    def reset(self):
        super().reset()
        self.events = Counter()
        self.return_pair = None
        self.lane_shift = [None] * 32

    def comb(self, inp):
        if self.state != 8:
            return super().comb(inp)
        q = self.queue.comb_pair(self.item, True, self.emit_row, self.row < 98,
                                 inp.get('out_ready', False), inp.get('out_pair_ready', False))
        pair_done = q['row1_push'] or (self.row == 98 and q['row0_push'])
        has_next = self.row < 98 or self.tile < 15
        next_row1 = self.row < (96 if self.tile == 15 else 98)
        mask = 0
        if has_next:
            if q['row0_push']:
                mask |= 3 << self.lane
            if q['row1_push'] and next_row1:
                mask |= 3 << (16 + self.lane)
        return dict(q=q, quant=int(q['row0_push']) + int(q['row1_push']),
                    seed_mask=mask, mac_mask=0, last_emit=pair_done, has_next=has_next)

    def tick(self, inp, c):
        if inp.get('reset'):
            return super().tick(inp, c)
        state, row, tile, col = self.state, self.row, self.tile, self.lane
        request = None
        if inp.get('layer_start'):
            self.return_pair = None
            self.events = Counter()
            self.lane_shift = [None] * 32
        if state == 4:
            request = (tile, self.chunk)
        elif state == 7 and self.inner == 63 and c['has_next']:
            request = ((tile + 1) % 16, 0)
        elif state == 8 and c['last_emit'] and c['has_next'] and col < 14:
            request = ((tile + 1) % 16, col // 2 + 1)
        if state == 8:
            q = c['q']
            self.events.update(dual=int(q['row0_push'] and q['row1_push']),
                               row0_only=int(q['row0_push'] and not q['row1_push']),
                               row1_only=int(q['row1_push'] and not q['row0_push']),
                               wait0=int(not self.emit_row and not q['room0']),
                               wait1=int(q['row1_attempt'] and not q['row1_push']))
            pairs = [[], []]
            for r, fire in enumerate((q['row0_push'], q['row1_push'])):
                if not fire:
                    continue
                for offset in range(2):
                    lane = r * 16 + col + offset
                    index = (row + r) * 256 + tile * 16 + col + offset
                    if self.products[lane] != 64 or self.seeds[lane] != 1:
                        raise RuntimeError('Q4 MAC/bias identity differs at output %d' % index)
                    shift = self.lane_shift[lane]
                    if shift != self.shifts[index % 256]:
                        raise RuntimeError('Q4 consumed wrong shift at output %d' % index)
                    pairs[r].append((index, rne(self.acc[lane], shift)))
                    self.products[lane] = self.seeds[lane] = 0
                    self.quantized += 1
        for lane in range(32) if c['seed_mask'] else ():
            if not c['seed_mask'] >> lane & 1:
                continue
            target = tile if state == 5 else (tile + 1) % 16
            column = lane % 16
            if self.return_pair != (target, column // 2):
                raise RuntimeError('Q4 seed did not consume its prior synchronous return')
            self.lane_shift[lane] = self.shifts[target * 16 + column]
        if state != 8:
            popped = super().tick(inp, c)
        else:
            popped = super().tick(inp, dict(c, quant=0, q=dict(q, pairs=pairs)))
            if c['last_emit']:
                self.emit_row = 0
                if col < 14:
                    self.lane += 2
                elif tile < 15:
                    self.tile, self.state = tile + 1, 6
                    self.inner = self.chunk = self.seed_ready = 0
                else:
                    self.state = 14
                    self.seed_ready = int(c['has_next'])
            elif q['row0_push']:
                self.emit_row = 1
        if request is not None:
            self.return_pair = request
            self.events['bias_shift_reads'] += 1
        if popped and self.queue.retired == 25344:
            paired = 2 * self.events['dual'] + self.events['row0_only'] + self.events['row1_only']
            if (paired != 12672 or self.events['dual'] + self.events['row0_only'] != 6400
                    or self.events['dual'] + self.events['row1_only'] != 6272
                    or self.events['bias_shift_reads'] != 6400):
                raise RuntimeError('Q4 pair or seed-read counts differ')
            self.completed.append(dict(events=dict(self.events), peak=dict(self.queue.peak)))
        return popped


def output_to_study(function):
    return FunctionType(function.__code__, dict(function.__globals__, REPORT=REPORT))


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def cold(cls, pacing, layer, prefix, commands):
    label = 'SR' if cls is ControlCore else 'Q4'
    result = output_to_study(run)(cls, pacing, layer, prefix, commands, WriteWrapper, label)
    if cls is Q4Core:
        result['queue_evidence'], = cls.instance.completed
    if (result['host_writes'], result['dma_reads'], result['dma_writes'],
            result['descriptors'], result['outputs']) != (11946,11936,12672,102,25344):
        raise RuntimeError('Cold payload, retirement or descriptor totals differ')
    if result['final_ack'] <= result['final_physical_commit']:
        raise RuntimeError('Final ACK must follow physical write')
    save('timing-%s-%s-%02d.json' % (label, pacing, layer), result)
    return result


def scenario(name):
    result = output_to_study(normal)(Q4Core, name)
    evidence = Q4Core.instance.completed
    if len(evidence) != 12:
        raise RuntimeError('Q4 continuous scenario did not complete twelve tasks')
    for frame, observed in zip(result['frames'], evidence):
        frame['queue_evidence'] = observed
    save('normal-'+name+'.json', result)
    return result


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    release = json.loads((ROOT/'reports/submission/ara-SR-release-20261105/completion.json').read_text())
    prefix, commands = output_to_study(parent_timing.observed_program)()
    baseline = cold(ControlCore, 'response_relative', 0, prefix, commands)
    if release['variant'] != 'ffn_ara_SR' or any(baseline[k] != v for k, v in ANCHORS.items()):
        raise RuntimeError('SR native anchor calibration differs')
    save('calibration.json', dict(passed=True, expected=ANCHORS, model=baseline,
                                 reference_cycles=release['cycles']))
    with ProcessPoolExecutor(max_workers=4) as pool:
        relative = [pool.submit(cold, Q4Core, 'response_relative', case, prefix, commands) for case in range(12)]
        fixed_sr = pool.submit(cold, ControlCore, 'conservative_IR', 0, prefix, commands)
        fixed_q4 = [pool.submit(cold, Q4Core, 'conservative_IR', case, prefix, commands) for case in range(12)]
        scenarios = [pool.submit(scenario, name) for name in ('mixed','mixed_paused','single')]
        relative_results = [job.result() for job in relative]
        fixed_sr_result = fixed_sr.result()
        fixed_results = [job.result() for job in fixed_q4]
        normal_results = [job.result() for job in scenarios]
    cycles = sum(row['cold_cycles'] for row in relative_results)
    sr_cycles = sum(release['cycles'])
    result = dict(calibrated=True, functional_passed=True, timing_eligible=cycles < sr_cycles,
                  sr_cycles_total=sr_cycles, candidate_cycles_total=cycles,
                  candidate_throughput=1800000000/cycles, cold_results=relative_results,
                  conservative_sr_case1=fixed_sr_result, conservative_q4=fixed_results,
                  normal_scenarios=normal_results, internal_ready_replayed=False,
                  hardware_measured=False)
    save('model-results.json', result)
    print('SR_Q4_MODEL_COMPLETE', cycles, sr_cycles, result['timing_eligible'], flush=True)


if __name__ == '__main__':
    main()

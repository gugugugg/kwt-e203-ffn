"""SR fixed FIFO-only first-row screening using the existing causal SoC model."""
import json
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import FunctionType

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sr_storage_study'
sys.path[:0] = [str(ROOT / 'scripts' / name) for name in
                ('c16_efficiency', 'column_parallel', 'taskflow_study')]

from models import ControlCore, WriteWrapper, parent_timing, run
from model_validate import normal

ANCHORS = dict(cold_cycles=98783, first_mac=29895, last_emit=98754,
               final_physical_commit=98782, final_ack=98784)
RELEASE = ROOT / 'reports/submission/ara-SR-release-20261105/completion.json'


class FifoOnlyQueue:
    """First row uses the existing FIFO and held; second row retains both banks."""

    def __init__(self):
        self.completed = []
        self.reset()

    def reset(self):
        self.fifo = [None] * 16
        self.fifo_count = self.fifo_read = self.fifo_write = 0
        self.row1 = [None] * 256
        self.row1_count = self.row1_read = self.row1_write = 0
        self.held, self.pending = [], []
        self.retired = 0
        self.peak = dict(fifo=0, row1=0, held=0, pending=0, total=0)
        self.events = Counter()

    def comb(self, item, push_valid, push_row1, out_ready, out_pair_ready):
        held, pending = len(self.held), len(self.pending)
        pop = 2 if out_pair_ready and held == 2 else int(out_ready and held > 0)
        space = 2 - held - pending + pop
        next_item = item + held + pending
        next_row1 = bool(next_item & 256)
        can_take = space > 0 and next_item < 25344
        capture1 = pending
        row1_room = self.row1_count + 2 <= 256 + capture1
        push1 = bool(push_valid and push_row1 and row1_room)
        read1 = bool(can_take and next_row1 and not push1 and self.row1_count > capture1)
        read_pair = bool(read1 and space >= 2 and (next_item & 255) != 255
                         and self.row1_count >= capture1 + 2)
        take = bool(can_take and not next_row1 and self.fifo_count > 0)
        row0_room = self.fifo_count + 2 <= 16 + int(take)
        return dict(pop_count=pop, read0=False, read1=read1,
                    issue=2 if read_pair else int(read1), capture1=capture1,
                    row1_push=push1, row0_push=bool(push_valid and not push_row1 and row0_room),
                    take=take, ready=row1_room if push_row1 else row0_room,
                    space=space, next_item=next_item, next_row1=next_row1,
                    row0_push_wait=bool(push_valid and not push_row1 and not row0_room),
                    row1_push_wait=bool(push_valid and push_row1 and not row1_room))

    def tick(self, c, pair, restart=False):
        if restart:
            self.reset()
            return []
        popped = self.held[:c['pop_count']]
        for token in popped:
            if token is None or token[0] != self.retired:
                raise RuntimeError('retirement identity differs at %d: %r' % (self.retired, token))
            self.retired += 1
        held = self.held[c['pop_count']:] + self.pending
        if c['take']:
            token = self.fifo[self.fifo_read]
            if token is None or token[0] != c['next_item']:
                raise RuntimeError('FIFO identity differs at %d: %r' % (c['next_item'], token))
            held.append(token)
            self.fifo[self.fifo_read] = None
            self.fifo_read = (self.fifo_read + 1) & 15
        for index in range(c['capture1']):
            self.row1[(self.row1_read + index) & 255] = None
        self.row1_read = (self.row1_read + c['capture1']) & 255
        new_pending = []
        if c['read1']:
            for index in range(c['issue']):
                token = self.row1[(self.row1_read + index) & 255]
                if token is None or token[0] != c['next_item'] + index:
                    raise RuntimeError('second-row bank identity differs at %d: %r' %
                                       (c['next_item'] + index, token))
                new_pending.append(token)
        if c['row0_push']:
            self.fifo_write = self.write_pair(self.fifo, self.fifo_write, pair)
        if c['row1_push']:
            self.row1_write = self.write_pair(self.row1, self.row1_write, pair)
        self.events.update(dict(
            fifo_takes=int(c['take']), fifo_push_words=2 * int(c['row0_push']),
            row1_read_words=c['issue'], row1_write_words=2 * int(c['row1_push']),
            fifo_full_cycles=int(self.fifo_count == 16),
            row0_quant_wait=int(c['row0_push_wait']), row1_quant_wait=int(c['row1_push_wait']),
            row0_wait_held_full=int(c['row0_push_wait'] and c['space'] == 0),
            row0_wait_older_row1=int(c['row0_push_wait'] and c['space'] > 0 and c['next_row1']),
            row1_write_blocks_read=int(c['row1_push'] and c['space'] > 0 and c['next_row1']),
            odd_pair_pops=int(c['pop_count'] == 2 and (self.retired & 1) == 1),
        ))
        self.fifo_count += 2 * int(c['row0_push']) - int(c['take'])
        self.row1_count += 2 * int(c['row1_push']) - c['capture1']
        self.held, self.pending = held, new_pending
        if not (0 <= self.fifo_count <= 16 and 0 <= self.row1_count <= 256
                and len(held) + len(new_pending) <= 2):
            raise RuntimeError('physical storage capacity exceeded')
        for name, value in dict(fifo=self.fifo_count, row1=self.row1_count, held=len(held),
                                pending=len(new_pending),
                                total=self.fifo_count + self.row1_count + len(held)).items():
            self.peak[name] = max(self.peak[name], value)
        if self.retired == 25344 and popped:
            expected = dict(fifo_takes=12800, fifo_push_words=12800, row1_read_words=12544,
                            row1_write_words=12544)
            if any(self.events[key] != value for key, value in expected.items()):
                raise RuntimeError('physical movement totals differ: %r' % self.events)
            self.completed.append(self.snapshot())
        return popped

    @staticmethod
    def write_pair(memory, pointer, pair):
        if pointer & 1 or memory[pointer] is not None or memory[pointer + 1] is not None:
            raise RuntimeError('paired bank write would overwrite live data at %d' % pointer)
        memory[pointer:pointer + 2] = pair
        return (pointer + 2) % len(memory)

    def snapshot(self):
        return dict(fifo_count=self.fifo_count, row1_count=self.row1_count,
                    held_count=len(self.held), pending_count=len(self.pending),
                    retired=self.retired, peak=dict(self.peak), events=dict(self.events))


class FifoOnlyCore(ControlCore):
    last_instance = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = FifoOnlyQueue()
        FifoOnlyCore.last_instance = self


class ObservedWrapper(WriteWrapper):
    last_instance = None

    def __init__(self):
        super().__init__()
        ObservedWrapper.last_instance = self

    def tick(self, cpu, c, cycle):
        self.last_cycle = cycle
        self.last_cpu = dict(cpu)
        return super().tick(cpu, c, cycle)


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def output_to_study(function):
    return FunctionType(function.__code__, dict(function.__globals__, REPORT=REPORT))


def progress_snapshot():
    core = FifoOnlyCore.last_instance
    if core is None:
        return {}
    return dict(state=core.state, row=core.row, tile=core.tile, lane=core.lane,
                emit_row=core.emit_row, item=core.item, input_count=core.input_count,
                queue=core.queue.snapshot())


def cold(label, layer, prefix, commands):
    cls = ControlCore if label == 'SR' else FifoOnlyCore
    try:
        result = output_to_study(run)(cls, 'response_relative', layer, prefix, commands,
                                      ObservedWrapper, label)
        if label != 'SR':
            result['queue_evidence'] = FifoOnlyCore.last_instance.queue.completed[0]
            result['ack_after_final_commit'] = result['final_ack'] > result['final_physical_commit']
            if result['host_writes'] != 11946 or not result['ack_after_final_commit']:
                raise RuntimeError('host loading count or final ACK order differs')
        save('timing-%s-response_relative-%02d.json' % (label, layer), result)
        return result
    except RuntimeError as exc:
        wrapper = ObservedWrapper.last_instance
        result = dict(passed=False, layer=layer, error=str(exc), snapshot=progress_snapshot())
        if wrapper is not None:
            result.update(last_cycle=wrapper.last_cycle, last_cpu=wrapper.last_cpu,
                          dma_reads=wrapper.memory.reads, dma_writes=wrapper.memory.writes,
                          descriptors=wrapper.engine.launches, dma_active=wrapper.engine.pd_active,
                          host_writes=wrapper.memory.host_writes)
        save('timing-%s-response_relative-%02d.json' % (label, layer), result)
        print('SR_STORAGE_COLD_FAIL', label, layer, str(exc), flush=True)
        return result


def scenario(label):
    try:
        result = output_to_study(normal)(FifoOnlyCore, label)
        for frame, evidence in zip(result['frames'], FifoOnlyCore.last_instance.queue.completed):
            frame['queue_evidence'] = evidence
        if len(FifoOnlyCore.last_instance.queue.completed) != 12:
            raise RuntimeError('continuous scenario lacks twelve completed frames')
    except RuntimeError as exc:
        result = dict(passed=False, scenario=label, error=str(exc), snapshot=progress_snapshot())
    save('normal-%s.json' % label, result)
    return result


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    release = json.loads(RELEASE.read_text(encoding='utf-8'))
    prefix, commands = output_to_study(parent_timing.observed_program)()
    baseline = cold('SR', 0, prefix, commands)
    matches = (release['variant'] == 'ffn_ara_SR' and release['cycles'] == [98783] * 12
               and baseline['passed'] and all(baseline[key] == value for key, value in ANCHORS.items()))
    save('calibration.json', dict(passed=matches, expected=ANCHORS, model=baseline,
                                  baseline_cycles=release['cycles'],
                                  anchor_basis='SR CPU12 release and calibrated C physical commit/ACK and inner anchors'))
    if not matches:
        raise RuntimeError('SR baseline calibration differs')
    with ProcessPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(cold, 'FIFO16', layer, prefix, commands) for layer in range(12)]
        scenarios = [pool.submit(scenario, label) for label in ('mixed', 'mixed_paused', 'single')]
        results = [task.result() for task in tasks]
        normal_results = [task.result() for task in scenarios]
    total = sum(row['cold_cycles'] for row in results) if all(row['passed'] for row in results) else None
    functional = all(row['passed'] for row in results + normal_results)
    save('model-results.json', dict(
        calibrated=True, functional_passed=functional, cold_results=results,
        normal_scenarios=normal_results, candidate_cycles_total=total,
        candidate_throughput=12 * 150000000 / total if total is not None else None,
        sr_cycles_total=sum(release['cycles']),
        timing_eligible=functional and total is not None and total <= sum(release['cycles']),
        measured_hardware=False, internal_ready_replayed=False,
        scope='Case1-calibrated response-relative CPU pacing. Other cases share the external instruction-gap assumption.'))
    print('SR_STORAGE_COMPLETE', functional, total, flush=True)


if __name__ == '__main__':
    main()


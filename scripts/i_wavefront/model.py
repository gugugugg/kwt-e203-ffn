"""Cycle model of the I release and the three fixed four-quartet schedules."""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/s1_bank_overlap'))
import model_overlap as transport

q16 = transport.q16
NAME = 'ffn_i_wavefront'
REPORT = ROOT / 'reports/optimization' / NAME
MODES = ('M0', 'W4', 'W4Z', 'W4Z_FT')
NATIVE = ROOT / 'reports/optimization/complete_soc/ffn_s1_bank_I'


class Output(q16.Output16):
    def reset(self):
        super().reset()
        self.prefix = 0
        self.early_words = 0

    def comb(self, item, single, pair, commit_rows=0):
        control = super().comb(item, single, pair, commit_rows)
        pop, index, _, _, _ = control
        if not (24576 <= index < 24832 and self.groups[0] == 24 and not self.ready[0]):
            return control
        committed = max(0, self.prefix * 4 - (index - 24576))
        space = 4 - len(self.held) - len(self.pending) + pop
        count = min(space, 2, committed)
        blocked = bool(count and commit_rows)
        return pop, index, 0 if blocked else count, blocked, commit_rows

    def write(self, group, words):
        super().write(group, words)
        if group == 24:
            assert words[0][0] == 24576 + self.prefix * 4
            self.prefix += 1

    def tick(self, control, cycle):
        _, index, count, _, _ = control
        if 24576 <= index < 24832 and self.groups[0] == 24 and not self.ready[0]:
            self.early_words += count
        return super().tick(control, cycle)


class Wave(q16.Core):
    def __init__(self, case, mode):
        self.stride = 65 if mode == 'W4' else 64
        super().__init__(case, 'Q16+PF2')
        if mode == 'W4Z_FT':
            self.queue = Output()
            self.queue.reset()

    def reset(self):
        super().reset()
        self.age = -1
        self.input_pipe = [None] * 4
        self.weight_q = [None] * 4
        self.weight_pipe = [None] * 4
        self.mac_cycles = [0] * 4
        self.fused = 0

    def phase(self, offset):
        if offset < 0:
            return None
        tile, k = divmod(offset, self.stride)
        return (tile, k) if tile < 16 and k < 64 else None

    def emission(self):
        for quartet in range(4):
            offset = self.age - 64 - quartet
            if offset >= 0 and offset % self.stride == 0 and offset // self.stride < 16:
                return offset // self.stride, quartet
        return None

    def comb(self, inp):
        if self.state != 7:
            return super().comb(inp)
        emission = self.emission()
        rows = min(4, 99 - self.row) if emission else 0
        return dict(out=self.queue.comb(self.item, inp.get('out_ready'), inp.get('out_pair_ready'), rows),
                    quant=bool(rows))

    def tick(self, inp, control):
        if self.state != 7 or inp.get('reset'):
            previous = self.state
            popped = super().tick(inp, control)
            if previous == 6 and self.state == 7:
                self.age = -1
                self.input_pipe = [None] * 4
                self.weight_q = [self.weight_address, None, None, None]
                self.weight_pipe = [None] * 4
            return popped

        group = self.row // 4
        valid_rows = min(4, 99 - self.row)
        popped = self.queue.tick(control['out'], self.cycle)
        leading = self.phase(self.age)
        if leading:
            tile, k = leading
            target = (tile + 1) % 16
            if tile < 15 or group < 24:
                if 56 <= k <= 63:
                    pair = k - 56
                    assert self.bias_return == (target, pair)
                    col = 16 * target + 2 * pair
                    self.shadow[pair] = target, tuple(zip(self.bias[col:col+2], self.shifts[col:col+2]))
                if 55 <= k <= 62:
                    self.bias_return = target, k - 55

        emission = self.emission()
        if emission:
            tile, quartet = emission
            words = []
            for row in range(valid_rows):
                for col in range(4 * quartet, 4 * quartet + 4):
                    lane = 16 * row + col
                    assert self.products[lane] == 64 and self.seeds[lane] == 1
                    result = q16.rne(self.acc[lane], self.shift[lane])
                    words.append(((self.row + row) * 256 + 16 * tile + col, result))
                    self.products[lane] = self.seeds[lane] = 0
                    if tile < 15 or self.row + 4 + row < 99:
                        target, pair = self.shadow[col // 2]
                        assert target == (tile + 1) % 16
                        bias, shift = pair[col % 2]
                        self.acc[lane], self.shift[lane] = q16.signed(bias, 36), shift
                        self.seeds[lane] = 1
            self.queue.write(group, words)
            self.commits += 1

        for quartet in range(4):
            token = self.phase(self.age - quartet)
            assert self.weight_pipe[quartet] == token
            if token is None:
                continue
            tile, k = token
            inputs = self.input_pipe[quartet]
            assert inputs is not None
            if self.stride == 64 and tile and not k:
                assert emission == (tile - 1, quartet)
                self.fused += 1
            self.mac_cycles[quartet] += 1
            for row, (identity, value) in enumerate(inputs):
                assert identity == (self.row + row) * 64 + k
                for col in range(4 * quartet, 4 * quartet + 4):
                    lane = 16 * row + col
                    assert self.seeds[lane] == 1 and self.products[lane] == k
                    self.acc[lane] = q16.signed(self.acc[lane] + value * self.weights[256*k + 16*tile + col], 36)
                    self.products[lane] += 1

        self.input_pipe = [self.input_q] + self.input_pipe[:3]
        self.weight_pipe = self.weight_q
        self.weight_q = [self.phase(self.age + 2 - quartet) for quartet in range(4)]
        request = self.weight_q[0]
        self.input_q = None
        if request:
            assert self.input_owner[group % 2] == group
            self.input_q = [self.input_banks[group % 2][r][request[1]] for r in range(valid_rows)]
            assert all(word is not None for word in self.input_q)
        self.accept_load(inp, request is not None, group % 2, self.cycle)
        self.age += 1
        self.inner = self.age
        if emission == (15, 3):
            self.input_owner[group % 2] = None
            self.queue.complete(group, self.cycle)
            self.state = 14
        return self.retire(popped)


def batch(mode, start, program, initial, first, gap):
    transport.staged.patch_parameter_limit()

    def make_core(case):
        nonlocal core
        core = Wave(case, mode) if mode != 'M0' else q16.Core(case, 'Q16+PF2')
        return core

    rows = []
    for case in range(start, start+3):
        core = None
        row = transport.simulate('I', 'response_relative', case, program, initial, first, gap, make_core=make_core)
        if mode != 'M0':
            assert core.mac_cycles == [25600] * 4 and core.commits == 1600
            assert core.fused == (1500 if core.stride == 64 else 0)
            row.update(quartet_mac_cycles=core.mac_cycles, fused=core.fused,
                       early_stash_halfwords=getattr(core.queue, 'early_words', 0),
                       stash_read_pauses=core.queue.blocked_reads, output_wait=core.output_wait)
        row['mode'] = mode
        rows.append(row)
    return rows


def native_anchors(case):
    log = (NATIVE / ('run_%02d.log' % (2 * case - 1))).read_text()
    marks = dict((k, int(v)) for k, v in re.findall(r'(\w+)=(\d+)', '\n'.join(
        line for line in log.splitlines() if line.startswith(('FFN_ROUND3_PHASE ', 'LOADING_DMA_COUNTS ',
                                                               'UNIFIED_PUBLIC_TASK_PASS ')))))
    return dict(first_mac=marks['first_mac'], last_emit=marks['last_emit'], final_ack=marks['last_ack'],
                final_physical_commit=marks['last_commit'], cold_cycles=marks['cycles'])


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    program, initial, first, gap, _ = transport.load_observation()
    rows = []
    modes = MODES if len(sys.argv) == 1 else tuple(sys.argv[1:])
    with ProcessPoolExecutor(max_workers=4) as pool:
        for mode in modes:
            jobs = [pool.submit(batch, mode, start, program, initial, first, gap) for start in range(0, 12, 3)]
            group = [row for job in jobs for row in job.result()]
            if mode == 'M0':
                for row in group:
                    actual = native_anchors(row['case'])
                    assert {k: row[k] for k in actual} == actual, (row['case'], actual)
            print(mode, sum(row['cold_cycles'] for row in group), group[0]['cold_cycles'], flush=True)
            rows.extend(group)
            (REPORT / ('model-' + mode + '.json')).write_text(json.dumps(group, indent=2) + '\n')
    if modes == MODES:
        totals = {mode: sum(r['cold_cycles'] for r in rows if r['mode'] == mode) for mode in MODES}
        order = sorted((mode for mode in MODES[1:] if totals[mode] < totals['M0']),
                       key=lambda mode: (totals[mode], MODES.index(mode)))
        (REPORT / 'model-selection.json').write_text(json.dumps(dict(totals=totals, order=order,
                     winner=order[0] if order else None), indent=2) + '\n')


if __name__ == '__main__':
    main()

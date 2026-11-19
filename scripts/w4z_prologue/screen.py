"""Cold-task causal screening of the fixed one- and two-group prologues."""
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_w4z_prologue'
PARENT = 'ffn_iw_W4Z_FT'
NATIVE = (ROOT / 'reports/optimization' / PARENT / 'received/full/native-evidence'
          / 'reports/optimization/complete_soc' / PARENT)
MODES = ('M0', 'P1', 'P2')
spec = importlib.util.spec_from_file_location('wavefront_model', ROOT / 'scripts/i_wavefront/model.py')
wave = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wave)
t = wave.transport
q16 = wave.q16
WEIGHT_WORDS = 8192
BIAS_WORD = t.PARAMETER_WORD + WEIGHT_WORDS


def quartet_layout(words):
    return [words[(tile * 64 + k) * 8 + quartet * 2 + pair]
            for tile in range(16) for quartet in range(4)
            for k in range(64) for pair in range(2)] + words[WEIGHT_WORDS:]


class Port(t.BankPort):
    def __init__(self, wrapper, mode):
        super().__init__(wrapper, mode)
        self.weights = self.biases = 0

    def committed(self, word):
        if t.PARAMETER_WORD <= word < BIAS_WORD:
            return word - t.PARAMETER_WORD < self.weights
        if BIAS_WORD <= word < t.PARAMETER_END:
            return word - BIAS_WORD < self.biases
        return self.shift_prefix == 64

    def stream_address(self, word):
        return word == t.PARAMETER_WORD + self.weights and self.weights < WEIGHT_WORDS

    def commit_host(self, addr, data, cycle):
        if t.PARAMETER_WORD <= addr < BIAS_WORD:
            assert addr == t.PARAMETER_WORD + self.weights
            self.weights += 1
            self.parameter_prefix += 1
            self.last_parameter_host = cycle
        elif BIAS_WORD <= addr < t.PARAMETER_END:
            assert addr == BIAS_WORD + self.biases
            self.biases += 1
            self.parameter_prefix += 1
        elif addr == t.READY_WORD and data == 1:
            assert self.biases == 256 and self.shift_prefix == 64
            self.stream_start = cycle
        else:
            super().commit_host(addr, data, cycle)


class Core(wave.Wave):
    def __init__(self, case, groups):
        self.groups = groups
        super().__init__(case, 'W4Z_FT')

    def reset(self):
        super().reset()
        self.weight_count = 0
        self.priv_weights = [[None] * 1024 for _ in range(16)]
        self.boot_position = self.reserve = self.bias_reads = 0
        self.bias_shadow = None
        self.boot_pipe = [None, None]
        self.boot_emit = None
        self.boot_done_cycle = None
        self.weight_block_cycles = self.weight_port_conflicts = 0
        self.boot_launch = []

    def layer_ready(self):
        return (self.parameter_count == 512 and self.shift_count == 128
                and self.input_count == self.groups * 256)

    def initial_seed_needed(self):
        return self.row == self.groups * 4

    @property
    def boot_mac(self):
        return self.state == 16 and self.boot_pipe[1] is not None

    def next_read(self):
        if self.state != 16 or self.reserve < self.groups:
            return None
        batch, offset = divmod(self.boot_position, self.groups * 64)
        if batch == 64 or self.weight_count < (batch + 1) * 256:
            return None
        tile, quartet = divmod(batch, 4)
        group, k = divmod(offset, 64)
        if not k and self.bias_shadow != tile:
            return None
        return group, tile, quartet, k

    def capacity(self, kind):
        if self.state == 2 and kind == 0:
            return self.input_count < 256 * self.groups
        if self.state != 16:
            return super().capacity(kind)
        if kind == 1:
            read = self.next_read()
            return self.weight_count < 16384 and (read is None or read[2] != (self.weight_count >> 8 & 3))
        if kind == 0:
            group = self.input_count // 256
            return group < 2 and self.input_owner[group % 2] in (None, group)
        return False

    def load(self, inp, read):
        if not inp.get('load'):
            return
        kind = inp['load_kind']
        if kind != 1:
            if kind == 5:
                col = self.shift_count * 2
                half = inp['load_word'] & 65535
                assert [half & 255, half >> 8] == self.shifts[col:col+2]
            self.accept_load(inp, read is not None, read[0] if read else 0, self.cycle)
            return
        address = inp['load_address']
        halves = 2 if inp['load_pair'] else 1
        if self.state == 2:
            assert address == 16384 + self.parameter_count
            if halves == 2:
                assert q16.signed(inp['load_word'], 32) == self.bias[self.parameter_count // 2]
            self.parameter_count += halves
            return
        assert self.state == 16 and address == self.weight_count
        for offset in range(halves):
            a = address + offset
            tile, quartet, k = a >> 10, a >> 8 & 3, a >> 2 & 63
            bank = quartet * 4 + (a & 3)
            location = ((k ^ (k >> 1)) << 4) | tile
            value = q16.signed(inp['load_word'] >> (16 * offset) & 65535, 16)
            assert value == self.weights[k * 256 + tile * 16 + bank]
            assert self.priv_weights[bank][location] is None
            assert read is None or quartet != read[2]
            self.priv_weights[bank][location] = value
        self.weight_count += halves

    def comb(self, inp):
        if self.state == 16:
            return dict(out=self.queue.comb(self.item, inp.get('out_ready'), inp.get('out_pair_ready'),
                                           4 if self.boot_emit else 0), quant=self.boot_emit is not None)
        return super().comb(inp)

    def tick(self, inp, control):
        if inp.get('reset'):
            self.reset()
            return []
        if self.state == 2:
            self.load(inp, None)
            if inp.get('layer_start'):
                assert self.layer_ready()
                self.queue.reset()
                self.state = 16
            return []
        if self.state != 16:
            return super().tick(inp, control)

        cycle = self.cycle
        read = self.next_read()
        popped = self.queue.tick(control['out'], cycle)
        if self.reserve < self.groups:
            self.queue.acquire(self.reserve)
            self.reserve += 1
        batch, offset = divmod(self.boot_position, self.groups * 64)
        target = batch // 4
        if batch % 4 == 3 and offset >= (self.groups - 1) * 64 + 4:
            target += 1
        if target < 16 and self.bias_shadow != target:
            self.bias_reads += 1
            if self.bias_reads == 9:
                self.bias_shadow = target
                self.bias_reads = 0
        if batch < 64 and self.weight_count < (batch + 1) * 256:
            self.weight_block_cycles += 1
        if read is not None and self.weight_count < 16384 and read[2] == (self.weight_count >> 8 & 3):
            self.weight_port_conflicts += 1

        if self.boot_emit:
            group, tile, quartet = self.boot_emit
            words = []
            for row in range(4):
                for col in range(4 * quartet, 4 * quartet + 4):
                    lane = row * 16 + col
                    assert self.products[lane] == 64 and self.seeds[lane] == 1
                    words.append(((4 * group + row) * 256 + 16 * tile + col,
                                  q16.rne(self.acc[lane], self.shift[lane])))
                    self.products[lane] = self.seeds[lane] = 0
            self.queue.write(group, words)
            self.commits += 1
            if tile == 15 and quartet == 3:
                self.input_owner[group] = None
                self.queue.complete(group, cycle)
                if group == self.groups - 1:
                    assert self.weight_count == 16384
                    self.boot_done_cycle = cycle
                    self.row = 4 * self.groups
                    self.state = 15
            self.boot_emit = None

        execute = self.boot_pipe[1]
        if execute:
            (group, tile, quartet, k), inputs, weights = execute
            for row, (identity, value) in enumerate(inputs):
                assert identity == (4 * group + row) * 64 + k
                for col, weight in enumerate(weights, 4 * quartet):
                    lane = row * 16 + col
                    if k == 0:
                        assert self.bias_shadow == tile
                        self.seed(row, col, tile)
                    assert self.products[lane] == k and self.seeds[lane] == 1
                    self.acc[lane] = q16.signed(self.acc[lane] + value * weight, 36)
                    self.products[lane] += 1
            self.mac_cycles[quartet] += 1
            if k == 63:
                self.boot_emit = group, tile, quartet

        token = None
        if read:
            group, tile, quartet, k = read
            assert self.input_owner[group] == group
            inputs = [self.input_banks[group][row][k] for row in range(4)]
            addr = ((k ^ (k >> 1)) << 4) | tile
            weights = [self.priv_weights[col][addr] for col in range(4 * quartet, 4 * quartet + 4)]
            assert all(v is not None for v in inputs + weights)
            token = read, inputs, weights
            if k == 0:
                self.boot_launch.append((cycle, group, tile, quartet))
            self.boot_position += 1
        self.boot_pipe = [token, self.boot_pipe[0]]
        self.load(inp, read)
        return self.retire(popped)


def prologue_program(program, groups):
    """Move descriptor templates, retaining CPU instruction gaps at the CSR edges."""
    commands = list(program[:11])

    def append(idx, data=None, gap=None):
        item = dict(program[idx])
        if data is not None:
            item['data'] = data
        if gap is not None:
            item['gap'] = gap
        commands.append(item)

    def descriptor(template, addr=None, words=None, gap=None):
        append(template, addr, gap)
        append(template+1, words)
        append(template+2)
        append(template+3)

    append(11)
    append(12, 16384)
    descriptor(13, 0xa0028000, 256)
    commands.extend(program[17:23])
    append(24)
    append(25)
    descriptor(27, words=128 * groups)
    append(23)
    append(26)
    append(11, gap=8)
    append(12)
    descriptor(13, words=8192)
    append(24, gap=9)
    append(25, 256 * groups)
    if groups == 1:
        commands.extend(program[31:])
    else:
        commands.extend(program[35:])
    return commands


def anchors(case):
    path = NATIVE / ('run_%02d.log' % (2 * case - 1))
    lines = [line for line in path.read_text().splitlines() if line.startswith(
        ('FFN_TRANSPORT_PHASE ', 'LOADING_DMA_COUNTS ', 'UNIFIED_PUBLIC_TASK_PASS '))]
    fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', '\n'.join(lines))}
    return {dest: fields[key] for dest, key in (
        ('first_mac', 'mac_first'), ('last_emit', 'last_emit'), ('final_physical_commit', 'last_commit'),
        ('final_ack', 'last_ack'), ('cold_cycles', 'cycles'))}


def batch(mode, start, program, initial, first, gap):
    t.staged.patch_parameter_limit(prologue=mode != 'M0')
    groups = 0 if mode == 'M0' else int(mode[-1])
    results = []
    for case in range(start, start + 3):
        core = wave.Wave(case, 'W4Z_FT') if not groups else Core(case, groups)
        args = dict(bootstrap=128 * groups, parameter_layout=quartet_layout, make_port=Port,
                    descriptor_count=53 if groups == 1 else 52) if groups else {}
        row = t.simulate('I', 'response_relative', case, program, initial, first, gap,
                         make_core=lambda _: core, **args)
        assert core.mac_cycles == [25600] * 4 and core.commits == 1600
        if mode == 'M0':
            actual = anchors(case + 1)
            assert {key: row[key] for key in actual} == actual, (row, actual)
        else:
            assert len(core.boot_launch) == groups * 64
            row.update(boot_done_cycle=core.boot_done_cycle, boot_launch=core.boot_launch,
                       boot_weight_wait_cycles=core.weight_block_cycles,
                       boot_weight_port_conflict_cycles=core.weight_port_conflicts,
                       output_generation_wait_cycles=core.output_wait,
                       output_generation_ready=core.queue.group_ready,
                       output_generation_freed=core.queue.group_freed)
        row['mode'] = mode
        results.append(row)
    return results


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    program, initial, first, gap, _ = t.load_observation()
    totals = {}
    modes = tuple(sys.argv[1:]) or MODES
    with ProcessPoolExecutor(max_workers=4) as pool:
        for mode in modes:
            commands = program if mode == 'M0' else prologue_program(program, int(mode[-1]))
            jobs = [pool.submit(batch, mode, i, commands, initial, first, gap) for i in range(0, 12, 3)]
            rows = [row for job in jobs for row in job.result()]
            totals[mode] = sum(row['cold_cycles'] for row in rows)
            (REPORT / ('model-' + mode + '.json')).write_text(json.dumps(rows, indent=2) + '\n')
            print(mode, totals[mode], rows[0]['cold_cycles'], flush=True)
    if all((REPORT / ('model-' + mode + '.json')).is_file() for mode in MODES):
        for mode in MODES:
            if mode not in totals:
                totals[mode] = sum(row['cold_cycles'] for row in json.loads(
                    (REPORT / ('model-' + mode + '.json')).read_text()))
        order = sorted((mode for mode in MODES[1:] if totals[mode] < totals['M0']),
                       key=lambda mode: (totals[mode], MODES.index(mode)))
        (REPORT / 'model-selection.json').write_text(json.dumps(dict(
            totals=totals, order=order, winner=order[0] if order else None), indent=2) + '\n')


if __name__ == '__main__':
    main()

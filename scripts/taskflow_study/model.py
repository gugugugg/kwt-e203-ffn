"""Clocked token/control model of frozen IR; data identities survive all storage moves."""
from collections import deque
from pathlib import Path
import csv
import json
import struct

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_taskflow_study'
MASK36 = (1 << 36) - 1


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def rne(value, shift):
    if shift not in range(13, 19):
        return 0
    q = value >> shift
    if q >= 32767:
        return 32767
    if q < -32768:
        return -32768
    remainder = value & ((1 << shift) - 1)
    half = 1 << (shift - 1)
    return q + int(remainder > half or (remainder == half and q & 1))


def vectors(layer=0):
    base = ROOT / 'build/optimization/ffn_transport/testdata'
    def words(name):
        return [v[0] for v in struct.iter_unpack('<h', (base / name).read_bytes())]
    x = words('linear_%02d_input.bin' % layer)
    p = words('layer_%02d_parameters.bin' % layer)
    b = [struct.unpack('<q', (base / ('layer_%02d_parameters.bin' % layer)).read_bytes()[32768 + i * 8:32776 + i * 8])[0] for i in range(256)]
    sh = (base / ('layer_%02d_shifts.bin' % layer)).read_bytes()
    return x, p[:16384], b, [signed(v, 8) for v in sh]


class OutputQueue:
    def __init__(self):
        self.reset()

    def reset(self):
        self.fifo = [None] * 16
        self.fifo_count = self.fifo_read = self.fifo_write = 0
        self.row0 = [None] * 128
        self.row1 = [None] * 256
        self.row0_count = self.row0_read = self.row0_write = 0
        self.row1_count = self.row1_read = self.row1_write = 0
        self.held = []
        self.pending = []
        self.pending_row1 = 0
        self.retired = 0
        self.peak = dict(fifo=0, row0=0, row1=0, total=0)

    def comb(self, item, push_valid, push_row1, out_ready, out_pair_ready):
        h, p = len(self.held), len(self.pending)
        pop = 2 if out_pair_ready and h == 2 else 1 if out_ready and h else 0
        capture0 = p if not self.pending_row1 else 0
        capture1 = p if self.pending_row1 else 0
        row1_room = self.row1_count + 2 <= 256 + capture1
        push1 = bool(push_valid and push_row1 and row1_room)
        space = 2 - h - p + pop
        next_item = item + h + p
        next_row1 = (next_item >> 8) & 1
        can_read = space != 0 and next_item < 25344
        read0 = bool(can_read and not next_row1 and self.row0_count > capture0)
        read1 = bool(can_read and next_row1 and not push1 and self.row1_count > capture1)
        read1_pair = bool(read1 and space >= 2 and (next_item & 255) != 255 and self.row1_count >= capture1 + 2)
        issue = 2 if read1_pair else int(read0 or read1)
        drain0 = bool(self.fifo_count and self.row0_count < 128 and not read0)
        row0_room = self.fifo_count + 2 <= 16 + int(drain0)
        push0 = bool(push_valid and not push_row1 and row0_room)
        return dict(pop_count=pop, capture0=capture0, capture1=capture1, read0=read0,
                    read1=read1, read1_pair=read1_pair, issue=issue, drain0=drain0,
                    row0_push=push0, row1_push=push1, ready=row1_room if push_row1 else row0_room)

    def tick(self, c, pair, restart=False):
        if restart:
            self.reset()
            return []
        popped = self.held[:c['pop_count']]
        for token in popped:
            if token is None or token[0] != self.retired:
                raise RuntimeError('Ordered token retirement differs: %r expected %d' % (token, self.retired))
            self.retired += 1
        next_held = self.held[c['pop_count']:] + self.pending
        new_pending = []
        if c['read0']:
            address = (self.row0_read + c['capture0']) & 127
            new_pending = [self.row0[address]]
        elif c['read1']:
            address = (self.row1_read + c['capture1']) & 255
            new_pending = [self.row1[(address + i) & 255] for i in range(c['issue'])]
        drained = self.fifo[self.fifo_read] if c['drain0'] else None
        if c['row0_push']:
            for i, token in enumerate(pair):
                self.fifo[(self.fifo_write + i) & 15] = token
            self.fifo_write = (self.fifo_write + 2) & 15
        if c['drain0']:
            self.row0[self.row0_write] = drained
            self.row0_write = (self.row0_write + 1) & 127
            self.fifo_read = (self.fifo_read + 1) & 15
        if c['row1_push']:
            for i, token in enumerate(pair):
                self.row1[(self.row1_write + i) & 255] = token
            self.row1_write = (self.row1_write + 2) & 255
        self.fifo_count += 2 * int(c['row0_push']) - int(c['drain0'])
        self.row0_count += int(c['drain0']) - c['capture0']
        self.row1_count += 2 * int(c['row1_push']) - c['capture1']
        self.row0_read = (self.row0_read + c['capture0']) & 127
        self.row1_read = (self.row1_read + c['capture1']) & 255
        self.held, self.pending = next_held, new_pending
        self.pending_row1 = int(bool(c['read1']))
        for name, value in [('fifo', self.fifo_count), ('row0', self.row0_count), ('row1', self.row1_count),
                            ('total', self.fifo_count + self.row0_count + self.row1_count + len(self.held))]:
            self.peak[name] = max(self.peak[name], value)
        return popped

    def snapshot(self):
        return {name: getattr(self, name) for name in ['fifo_count', 'fifo_read', 'fifo_write',
            'row0_count', 'row0_read', 'row0_write', 'row1_count', 'row1_read', 'row1_write', 'pending_row1']} | dict(held_count=len(self.held), pending_count=len(self.pending))


class Core:
    def __init__(self, initial_state=1, layer=0, numeric=True):
        self.numeric = numeric
        self.x, self.w, self.bias, self.shifts = vectors(layer) if numeric else ([], [], [], [])
        self.queue = OutputQueue()
        self.reset()
        self.state = initial_state
        if initial_state == 2:
            self.parameter_count, self.shift_count = 17408, 128

    def reset(self):
        self.state = 0
        self.row = self.tile = self.lane = self.inner = self.chunk = self.item = self.emit_row = 0
        self.input_count = self.parameter_count = self.shift_count = 0
        self.seed_ready = 0
        self.acc = [0] * 16
        self.products = [0] * 16
        self.seeds = [0] * 16
        self.quantized = 0
        self.queue.reset()

    def complete(self):
        return self.input_count >= (self.row + (1 if self.row == 98 else 2)) * 64

    def capacity(self, kind):
        prefetch = self.state == 7 and self.inner < 63
        read = (self.state == 6 and self.complete()) or prefetch
        return (self.state == 2 and kind in [1, 5]) or (kind == 0 and self.state >= 3 and
            self.input_count < 6336 and self.input_count < (self.row + 4) * 64 and not read)

    def comb(self, inp):
        q = self.queue.comb(self.item, self.state == 8, self.emit_row, inp.get('out_ready', False), inp.get('out_pair_ready', False))
        quant = bool(self.state == 8 and q['ready'])
        has_next = self.row < 98 or self.tile < 31
        last_emit = bool(self.emit_row or self.row == 98)
        next_row1 = self.row < (96 if self.tile == 31 else 98)
        seed_mask = mac_mask = 0
        for lane in range(16):
            r, col = divmod(lane, 8)
            seed = (self.state == 5 and self.chunk == col // 2 and (r == 0 or self.row < 98)) or (
                quant and has_next and self.emit_row == r and self.lane // 2 == col // 2 and (r == 0 or next_row1))
            seed_mask |= int(seed) << lane
            mac_mask |= int(self.state == 7 and (r == 0 or self.row < 98)) << lane
        return dict(q=q, quant=quant, seed_mask=seed_mask, mac_mask=mac_mask,
                    last_emit=last_emit, has_next=has_next)

    def tick(self, inp, c):
        if inp.get('reset'):
            self.reset()
            return []
        pair = []
        if c['quant']:
            base_lane = self.emit_row * 8 + self.lane
            for lane in [base_lane, base_lane + 1]:
                if self.products[lane] != 64 or self.seeds[lane] != 1:
                    raise RuntimeError('MAC/bias identity differs at lane %d: %d/%d' % (lane, self.products[lane], self.seeds[lane]))
                index = (self.row + self.emit_row) * 256 + self.tile * 8 + lane % 8
                value = rne(self.acc[lane], self.shifts[index % 256]) if self.numeric else 0
                pair.append((index, value))
                self.products[lane] = self.seeds[lane] = 0
                self.quantized += 1
        popped = self.queue.tick(c['q'], pair, inp.get('layer_start', False))
        for lane in range(16):
            if c['seed_mask'] >> lane & 1:
                target_tile = self.tile if self.state == 5 else (self.tile + 1) % 32
                col = target_tile * 8 + lane % 8
                self.acc[lane] = signed(self.bias[col], 36) if self.numeric else 0
                self.seeds[lane] += 1
            elif c['mac_mask'] >> lane & 1:
                if self.numeric:
                    row = self.row + lane // 8
                    self.acc[lane] = signed(self.acc[lane] + self.x[row * 64 + self.inner] * self.w[self.inner * 256 + self.tile * 8 + lane % 8], 36)
                self.products[lane] += 1
        old_state, old_seed = self.state, self.seed_ready
        if inp.get('layer_start'):
            self.seed_ready = 0
        else:
            if old_state == 3 and old_seed:
                self.seed_ready = 0
            if c['quant'] and c['has_next'] and c['last_emit'] and self.lane == 6:
                self.seed_ready = 1
        complete = self.complete()
        if old_state == 0:
            self.state = 1
        elif old_state == 1 and inp.get('start'):
            self.parameter_count = self.shift_count = 0
            self.state = 2
        elif old_state == 2 and inp.get('layer_start'):
            self.row = self.tile = self.item = self.lane = self.inner = self.emit_row = 0
            self.state = 15
        elif old_state == 15 and complete:
            self.state = 3
        elif old_state == 3:
            self.chunk = 0
            if old_seed:
                self.inner, self.state = 0, 6
            else:
                self.state = 4
        elif old_state == 4:
            self.state = 5
        elif old_state == 5:
            if self.chunk == 3:
                self.inner, self.state = 0, 6
            else:
                self.chunk += 1
                self.state = 4
        elif old_state == 6 and complete:
            self.state = 7
        elif old_state == 7:
            if self.inner == 63:
                self.lane = self.emit_row = 0
                self.state = 8
            else:
                self.inner += 1
        elif old_state == 8 and c['quant']:
            if not c['last_emit']:
                self.emit_row = 1
            else:
                self.emit_row = 0
                if self.lane < 6:
                    self.lane += 2
                elif self.tile < 31:
                    self.tile += 1
                    self.state = 3
                else:
                    self.state = 14
        elif old_state == 14:
            if self.row == 98:
                self.state = 12
            else:
                self.row += 2
                self.tile = self.lane = 0
                self.state = 15
        if inp.get('load'):
            kind = inp['load_kind']
            count = 2 if inp.get('load_pair') and kind != 5 else 1
            name = {0: 'input_count', 1: 'parameter_count', 5: 'shift_count'}[kind]
            if inp['load_address'] != getattr(self, name):
                raise RuntimeError('Load prefix differs for kind %d' % kind)
            setattr(self, name, getattr(self, name) + count)
        if c['q']['pop_count']:
            if self.item + c['q']['pop_count'] == 25344:
                self.state = 0
                self.input_count = self.parameter_count = self.shift_count = 0
            else:
                self.item += c['q']['pop_count']
        return popped

    def snapshot(self):
        return {name: getattr(self, name) for name in ['state', 'row', 'tile', 'lane', 'inner', 'chunk',
            'item', 'emit_row', 'input_count', 'parameter_count', 'shift_count', 'seed_ready']} | self.queue.snapshot()


def trace_rows(path):
    with Path(path).open() as stream:
        for raw in csv.DictReader(stream):
            yield {name: None if 'x' in value.lower() or 'z' in value.lower() else int(value, 16) for name, value in raw.items()}


def validate_core(path, initial_state=2):
    core = Core(initial_state=initial_state)
    rows = 0
    mismatches = []
    retired = []
    for row in trace_rows(path):
        rows += 1
        snapshot = core.snapshot()
        differences = {k: (v, row[k]) for k, v in snapshot.items() if v != row[k]}
        if differences:
            mismatches.append(dict(cycle=row['cycle'], fields=differences))
            break
        fire = row['pio_cmd_valid'] and row['pio_cmd_ready']
        inp = dict(out_ready=bool(fire and row['pio_cmd_read'] and row['pio_cmd_addr'] == 0x20),
                   out_pair_ready=bool(fire and row['pio_cmd_read'] and row['pio_cmd_addr'] == 0x34),
                   start=row['core_start'], layer_start=row['core_layer_start'], load=row['core_load'],
                   load_kind=row['load_kind'], load_address=row['load_address'], load_pair=row['core_load_pair'], reset=row['soft_reset'])
        c = core.comb(inp)
        expected = dict(quant=int(c['quant']), mac_mask=c['mac_mask'], seed_mask=c['seed_mask'])
        expected.update({k: int(c['q'][k]) for k in ['pop_count', 'read0', 'read1', 'drain0', 'row0_push', 'row1_push']})
        differences = {k: (v, row[k]) for k, v in expected.items() if v != row[k]}
        if differences:
            mismatches.append(dict(cycle=row['cycle'], combinational=differences))
            break
        if core.queue.held:
            if (core.queue.held[0][1] & 65535) != row['out_low']:
                mismatches.append(dict(cycle=row['cycle'], output_value=(core.queue.held[0], row['out_low'])))
                break
        retired.extend(core.tick(inp, c))
    result = dict(passed=not mismatches and len(retired) == 25344, rows_compared=rows,
                  outputs=len(retired), quantized=core.quantized, queue_peak=core.queue.peak,
                  mismatches=mismatches, boundary='Core input/output contract only; wrapper and system validation separate',
                  internal_ready_replayed=False, arithmetic='Exact signed36 modular MAC and RNE from original vectors')
    (REPORT / 'local-core-model-check.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    print(json.dumps(validate_core(REPORT / 'local-events.csv'), indent=2))

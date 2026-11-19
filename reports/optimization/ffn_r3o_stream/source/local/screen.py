"""Causal R3O/BIDIR/packed-input screen against a native observation."""
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_r3o_stream'
OBS = REPORT / 'received/observation/native-evidence' / REPORT.relative_to(ROOT) / 'observation'
sys.path.insert(0, str(ROOT / 'scripts/sr_pr1'))
import model_screen as sr
from model import trace_rows


def load_model(name, directory):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / directory / 'screen.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r3o = load_model('published_r3o_model', 'sr_r3o')
bidir = load_model('bidir_model', 'sr_transport_next')
MODES = ('M0', 'M1', 'M2', 'M3')
ANCHORS = dict(first_mac=29960, last_row0_emit=87099, last_emit=87101, final_physical_commit=87625,
               final_ack=87627, cold_cycles=87626)


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n')


def input_read(cmd):
    return cmd['read'] and 0xa0000000 <= cmd['address'] < 0xa0003180 and cmd['address'] % 4 == 0


def repack(words):
    samples = [half for word in words for half in (word & 65535, word >> 16)]
    stream = [samples[group * 192 + row * 64 + k]
              for group in range(33) for k in range(64) for row in range(3)]
    return [lo | hi << 16 for lo, hi in zip(stream[::2], stream[1::2])]


class StreamCore(r3o.Row3Core):
    def __init__(self, case, packed):
        self.packed = packed
        super().__init__(layer=case)

    def reset(self):
        super().reset()
        self.input_banks = [[None] * 128 for _ in range(3)]
        self.input_q = self.operands = None
        self.input_write_beats = self.input_writes = 0

    def tick(self, inp, control):
        if inp.get('reset'):
            return super().tick(inp, control)
        read = None
        if self.state == 6 and self.complete():
            read = 0
        elif self.state == 7 and self.inner < 62:
            read = self.inner + 2
        group = self.row // 3
        if self.state == 7 and self.inner >= 0:
            identities = [(group * 3 + row) * 64 + self.inner for row in range(3)]
            if self.operands is None or [cell[0] for cell in self.operands] != identities:
                raise RuntimeError('MAC does not see the registered input operand')
            for identity, value in self.operands:
                self.x[identity] = value
        if self.state == 7 and self.inner < 63:
            self.operands = self.input_q
        if read is not None:
            self.input_q = [bank[(group & 1) * 64 + read] for bank in self.input_banks]
            if any(cell is None for cell in self.input_q):
                raise RuntimeError('Read of an uninitialized private input SRAM word')
        if inp.get('load') and inp['load_kind'] == 0:
            count = 2 if inp['load_pair'] else 1
            if read is not None or self.input_count + count > min(6336, (self.row + 6) * 64):
                raise RuntimeError('Private SRAM read/write or generation collision')
            for offset in range(count):
                block, index = divmod(self.input_count + offset, 192)
                if self.packed:
                    k, row = divmod(index, 3)
                else:
                    row, k = divmod(index, 64)
                identity = (block * 3 + row) * 64 + k
                value = inp['input_word'] >> (16 * offset) & 65535
                self.input_banks[row][(block & 1) * 64 + k] = identity, sr.signed(value, 16)
            self.input_write_beats += 1
            self.input_writes += count
        return super().tick(inp, control)


class FastMemory(bidir.EarlyMemory):
    def qualifies(self, cmd):
        return super().qualifies(cmd) or self.wrapper.fast_input and input_read(cmd)


class StreamWrapper(bidir.TransportWrapper):
    def __init__(self, mode, case):
        super().__init__('SR' if mode == 'M0' else 'PRF_W1')
        self.mode, self.packed, self.fast_input = mode, mode in ('M2', 'M3'), mode == 'M3'
        self.core = StreamCore(case, self.packed)
        self.memory = sr.WriteMemory(self) if mode == 'M0' else FastMemory(self)

    def comb(self, cpu):
        c = super().comb(cpu)
        e = self.engine
        if self.fast_input and e.pd_active and not e.output_transfer and e.pd_count == 2 and e.source_remaining:
            pio = c['pio_return']
            if (input_read(c['commands']['memory']) and pio['valid'] and
                    (e.pd_dest_pending or c['commands']['pio']['valid'] and pio['ready'])):
                e.returned_credit = True
                c = sr.WriteWrapper.comb(self, cpu)
        inp = c['core_in']
        if inp['load'] and inp['load_kind'] == 0:
            inp['input_word'] = self.packed_high if c['flush'] else c['command']['data']
            if self.packed and c['packed']:
                inp['load_pair'] = True
        return c

    def tick(self, cpu, c, cycle):
        paired = self.packed and c['packed'] and self.load_kind == 0
        result = super().tick(cpu, c, cycle)
        if paired:
            self.pack_pending = 0
            self.load_address += 1
        return result


def read_program():
    trace = OBS / 'events.csv'
    prefix, commands = [], []
    first_launch = request = None
    for row in trace_rows(trace):
        cycle = row['cycle']
        if first_launch is None:
            prefix.append(row)
            if row['descriptor']:
                first_launch = cycle
        elif row['host_cmd_valid'] or row['shared_cpu_cmd_valid']:
            raise RuntimeError('Host or shared CPU issued a request after launch')
        if request is None and row['cpu_cmd_valid']:
            request = dict(sr.cpu_request(row), start=cycle)
        if request is not None and row['cpu_rsp_valid'] and row['cpu_rsp_ready']:
            request['response'] = cycle
            if commands:
                request['gap'] = request['start'] - commands[-1]['response']
            commands.append(request)
            request = None
    later = [cmd for cmd in commands if cmd['start'] > first_launch]
    previous = commands[commands.index(later[0])-1]['response']
    return prefix, later, previous


def simulate(mode, pacing, case, prefix, commands, prior, compare=None):
    image, expected = sr.frozen_image(case)
    if mode in ('M2', 'M3'):
        image.update(enumerate(repack([image[i] for i in range(3168)])))
    wrapper = StreamWrapper(mode, case)
    core, memory, e = wrapper.core, wrapper.memory, wrapper.engine
    for sample in prefix:
        row = dict(sample)
        address = row['host_cmd_addr']
        if row['host_cmd_valid'] and not row['host_cmd_read'] and address in image:
            row['host_cmd_wdata'] = image[address]
        memory.context(row)
        cpu = sr.cpu_request(row)
        wrapper.tick(cpu, wrapper.comb(cpu), row['cycle'])
    due = prior + commands[0]['gap']
    index = retired = 0
    accepted = False
    first_mac = last_row0_emit = last_emit = commit = ack = first_write = None
    desc, counts = [], dict(mac=0, fill=0, input_wait=0, dma_input_wait=0, quant_stall=0)
    outstanding = None
    divergence = []
    response_cycles = []
    for cycle in range(prefix[-1]['cycle']+1, 200000):
        memory.context(sr.empty_external())
        cpu = sr.idle_cpu()
        if index < len(commands) and not accepted and cycle >= due:
            cpu.update({key: commands[index][key] for key in ('read','address','data','mask')}, valid=1)
        c = wrapper.comb(cpu)
        if cpu['valid'] and c['cpu_ready']:
            accepted = True
        if accepted and c['cpu_valid']:
            response_cycles.append(cycle)
            accepted = False
            index += 1
            if index < len(commands):
                due = cycle + commands[index]['gap']
                if pacing == 'fixed_cpu':
                    due = max(due, commands[index]['start'])
        if core.state == 7:
            counts['fill'] += int(core.inner < 0)
            counts['mac'] += int(core.inner >= 0)
            if core.inner >= 0 and first_mac is None:
                first_mac = cycle
        cc = core.comb(c['core_in'])
        if cc['quant']:
            last_emit = cycle
            if core.emit_row == 0:
                last_row0_emit = cycle
        counts['quant_stall'] += int(core.state == 8 and not cc['quant'])
        counts['input_wait'] += int(core.state in (6, 15) and not core.complete())
        counts['dma_input_wait'] += int(e.pd_active and not e.output_transfer and wrapper.load_kind == 0
                                        and not core.capacity(0))
        if c['launch']:
            desc.append(dict(cycle=cycle, kind=wrapper.load_kind, **c['launch']))
        m = c['memory']
        if m['valid'] and m['rsp_ready']:
            if outstanding is None:
                raise RuntimeError('Response without a DMA owner at %d' % cycle)
            if outstanding['read'] and m['data'] != image[(outstanding['address']-0xa0000000)//4]:
                raise RuntimeError('Incorrect DMA response at %d' % cycle)
            outstanding = None
        if m['fire'] and m['grant']:
            if not m['physical'] or m['host_fire'] or outstanding is not None:
                raise RuntimeError('DMA transfer violated the shared physical port')
            outstanding = m['selected']
        if compare is not None and cycle in compare and len(divergence) < 12:
            row = compare[cycle]
            values = dict(core_state=(10 if core.state == 7 and core.inner < 0 else core.state),
                          row=core.row,tile=core.tile,emit_row=core.emit_row,lane=core.lane,
                          input_count=core.input_count, fifo_count=len(core.queue.fifo),
                          core_jp_quant_commit=int(cc['quant']), dma_pd_count=e.pd_count,
                          output_queue_held_count=len(core.queue.held),
                          output_queue_pending_count=len(core.queue.pending), physical_accept=int(m['physical']))
            actual = {key: [value, row[key]] for key, value in values.items() if value != row[key]}
            if actual:
                divergence.append(dict(cycle=cycle, model_native=actual))
        active = e.pd_active
        for identity, value in wrapper.tick(cpu, c, cycle):
            if identity != retired or expected[retired] != value:
                raise RuntimeError('Golden result differs at index %d' % retired)
            retired += 1
        if memory.writes and first_write is None:
            first_write = memory.commits[0][0]
        if memory.writes == 12672 and commit is None:
            commit = memory.commits[-1][0]
            for i, (_, address, data) in enumerate(memory.commits):
                packed = (expected[2*i]&65535) | ((expected[2*i+1]&65535)<<16)
                if address != 0xa0010000+4*i or data != packed:
                    raise RuntimeError('Physical output mismatch at word %d' % i)
        if commit is not None and active and not e.pd_active:
            ack = cycle
            break
    totals = (memory.host_writes, memory.reads, memory.writes, e.launches, retired,
              counts['mac'], counts['fill'], core.input_writes)
    if totals != (11946,11936,12672,68,25344,33792,528,6336) or ack is None or ack <= commit:
        raise RuntimeError('Cold task counts differ: %s' % (totals,))
    return dict(mode=mode,pacing=pacing,case=case+1,cold_cycles=commit+1,first_mac=first_mac,
                last_emit=last_emit,last_row0_emit=last_row0_emit,final_physical_commit=commit,final_ack=ack,first_output_commit=first_write,
                host_writes=totals[0],host_payload=11936,dma_reads=totals[1],dma_writes=totals[2],
                descriptors=totals[3],ordered_outputs=retired,private_input_write_beats=core.input_write_beats,
                counts=counts,queue_peak=core.queue.peak,descriptor_trace=desc,
                divergence=divergence,cpu_responses=response_cycles)


def main():
    prefix, commands, prior = read_program()
    rows = {}
    for row in trace_rows(OBS / 'events.csv'):
        row.update({key.replace('.', '_'): value for key, value in row.items() if '.' in key})
        rows[row['cycle']] = row
    base = simulate('M0','response_relative',0,prefix,commands,prior,rows)
    verified = {k: base[k] for k in ANCHORS}
    save('calibration.json', dict(passed=verified==ANCHORS, expected=ANCHORS, measured=verified,
                                 model=base, native_phase_marker="FFN_ROUND3_PHASE.last_emit monitors row0 fifo_push",
                                 prior_model_uses_SR_gaps=True, prior_model_excess_cycles=62,
                                 quant_stalls_model_and_native=9528))
    print('CALIBRATION', verified, base['divergence'][:4], flush=True)
    if verified != ANCHORS or base['divergence']:
        raise RuntimeError('Resolve native baseline divergence before selecting a candidate')
    runs = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        pending = [pool.submit(simulate,mode,pacing,case,prefix,commands,prior)
                   for pacing in ('response_relative','fixed_cpu') for mode in MODES for case in range(12)]
        for work in pending:
            row = work.result()
            runs.append(row)
            print('R3O_STREAM_MODEL',row['mode'],row['pacing'],row['case'],row['cold_cycles'],
                  row['private_input_write_beats'],row['counts']['quant_stall'],flush=True)
    totals = {pacing:{mode:sum(row['cold_cycles'] for row in runs
                 if row['pacing']==pacing and row['mode']==mode) for mode in MODES}
              for pacing in ('response_relative','fixed_cpu')}
    primary = totals['response_relative']
    selected = min(MODES,key=primary.get)
    save('model-selection.json',dict(passed=True,selected=None if selected=='M0' else selected,
        cycles_total=totals,throughput={mode:1800000000/value for mode,value in primary.items()},
        measured_hardware=False,internal_ready_replayed=False,runs=runs))
    print('R3O_STREAM_SELECTION',selected,totals,flush=True)


if __name__ == '__main__':
    main()

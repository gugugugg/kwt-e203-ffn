"""Response-relative CPU request pacing around the calibrated physical-port model."""
import json
import struct
import numpy as np
from core_model import ROOT, Core, ColumnCore, SerialColumnCore, vectors
from model import trace_rows, rne
from native_model import NativeWrapper, NATIVE, cpu_request
from native_simulate import empty_external, idle_cpu

REPORT = ROOT/'reports/optimization/ffn_column_parallel/models'


def observed_program():
    prefix, commands = [], []
    request = None
    for row in trace_rows(NATIVE/'native-events.csv'):
        if row['cycle'] <= 12113: prefix.append(row)
        if request is None and row['cpu_cmd_valid']:
            request = dict(start=row['cycle'], read=row['cpu_cmd_read'], address=row['cpu_cmd_addr'],
                           data=row['cpu_cmd_wdata'], mask=row['cpu_cmd_wmask'])
        if request is not None and row['cpu_rsp_valid'] and row['cpu_rsp_ready']:
            request['response_cycle'] = row['cycle']
            commands.append(request)
            request = None
    for i, command in enumerate(commands):
        command['gap'] = command['start'] - commands[i-1]['response_cycle'] if i else command['start']
    (REPORT/'observed-cpu-program.json').write_text(json.dumps(commands, indent=2))
    return prefix, [c for c in commands if c['start'] > 12113]


def payload(layer):
    folder = ROOT/'build/optimization/ffn_transport/testdata'
    result = {}
    for start, filename in [(0, 'linear_%02d_input.bin'), (0x8000, 'layer_%02d_parameters.bin'),
                            (0xe800, 'layer_%02d_shifts.bin')]:
        data = (folder/(filename % layer)).read_bytes()
        result.update((start+i, value[0]) for i, value in enumerate(struct.iter_unpack('<I', data)))
    return result


def run(cls, pacing, layer, prefix, commands):
    wrapper = NativeWrapper()
    wrapper.core = cls(layer=layer)
    data = payload(layer)
    x, w, bias, shifts = vectors(layer)
    sums = np.array(x, dtype=np.int64).reshape(99, 64) @ np.array(w, dtype=np.int64).reshape(64, 256)
    sums += np.array(bias, dtype=np.int64)
    expected = [rne(int(v), shifts[i % 256]) for i, v in enumerate(sums.reshape(-1))]
    for original in prefix:
        row = dict(original)
        if row['host_cmd_valid'] and not row['host_cmd_read'] and row['host_cmd_addr'] in data:
            row['host_cmd_wdata'] = data[row['host_cmd_addr']]
        wrapper.memory.context(row)
        cpu = cpu_request(row)
        c = wrapper.comb(cpu)
        wrapper.tick(cpu, c, row['cycle'])
    index, accepted, due = 0, False, 12113 + commands[0]['gap']
    retired, launches = 0, []
    counts = dict(mac_clocks=0, contributions=0, quant_pairs=0, quant_blocked=0,
                  input_missing=0, input_macro_reads=0, weight_macro_reads=0,
                  bias_requests=0, shift_requests=0, tiles=0, row0_read_drain_conflict=0,
                  row1_push_read_conflict=0)
    last_commit = ack = None
    for cycle in range(12114, 400000):
        wrapper.memory.context(empty_external())
        cpu = idle_cpu()
        if index < len(commands) and cycle >= due and not accepted:
            cpu.update({k: commands[index][k] for k in ['read', 'address', 'data', 'mask']})
            cpu['valid'] = 1
        c = wrapper.comb(cpu)
        core, q = wrapper.core, wrapper.core.queue
        cc = core.comb(c['core_in'])
        if cpu['valid'] and c['cpu_ready']: accepted = True
        if accepted and c['cpu_valid']:
            index += 1
            accepted = False
            if index < len(commands):
                due = cycle + commands[index]['gap']
                if pacing == 'conservative_IR': due = max(due, commands[index]['start'])
        if c['launch']: launches.append(dict(cycle=cycle, **c['launch']))
        rows = 1 if core.row == 98 else 2
        read_input = core.state == 6 and core.complete() or core.state == 7 and core.inner < 63 and (
            cls is not SerialColumnCore or core.half == 1)
        counts['input_macro_reads'] += rows * int(read_input)
        if cls is SerialColumnCore:
            weight_read = core.state == 6 and core.complete() or core.state == 7 and (core.half == 0 or core.inner < 63)
            counts['weight_macro_reads'] += 8 * int(weight_read)
        else: counts['weight_macro_reads'] += (8 if cls is Core else 16) * int(read_input)
        request_bias = core.state == 4 or core.state == 7 and core.inner == 63 and cc['has_next'] and (
            cls is not SerialColumnCore or core.half == 1) or cc['quant'] and cc['has_next'] and cc['last_emit'] and core.lane < (6 if cls is Core else 14)
        counts['bias_requests'] += int(request_bias)
        counts['shift_requests'] += int(request_bias)
        counts['tiles'] += core.state == 6 and core.complete()
        counts['mac_clocks'] += core.state == 7
        counts['contributions'] += cc['mac_mask'].bit_count()
        counts['quant_pairs'] += cc['quant']
        counts['quant_blocked'] += core.state == 8 and not cc['quant']
        counts['input_missing'] += core.state in [6, 15] and not core.complete()
        counts['row0_read_drain_conflict'] += bool(q.fifo_count and cc['q']['read0'])
        counts['row1_push_read_conflict'] += bool(cc['q']['row1_push'] and len(q.held)+len(q.pending)<2 and q.row1_count)
        active = wrapper.engine.pd_active
        for item, value in wrapper.tick(cpu, c, cycle):
            if item != retired or value != expected[item]:
                raise RuntimeError('Cold model ordered/value mismatch at %d' % item)
            retired += 1
        if wrapper.memory.writes == 12672 and last_commit is None:
            last_commit = wrapper.memory.commits[-1][0]
            for i, (_, address, value) in enumerate(wrapper.memory.commits):
                packed = (expected[2*i] & 65535) | (expected[2*i+1] & 65535) << 16
                if address != 0xa0010000+i*4 or value != packed:
                    raise RuntimeError('Physical write identity differs at %d' % i)
        if last_commit is not None and active and not wrapper.engine.pd_active:
            ack = cycle
            break
    else: raise RuntimeError('Cold model did not finish')
    result = dict(passed=True, model=cls.__name__, pacing=pacing, layer=layer,
        cold_cycles=last_commit+1, final_physical_commit=last_commit, final_ack=ack,
        outputs=retired, dma_reads=wrapper.memory.reads, dma_writes=wrapper.memory.writes,
        descriptors=wrapper.engine.launches, host_writes=wrapper.memory.host_writes,
        counts=counts, queue_peak=q.peak, launches=launches, measured_hardware=False,
        internal_ready_replayed=False, external_payload_placed_early=False,
        scope='Case1-calibrated component and CPU response-gap model; other layers use the same external instruction-gap assumption')
    if retired != 25344 or wrapper.memory.reads != 11936 or wrapper.engine.launches != 102:
        raise RuntimeError('Cold task totals differ')
    path = REPORT/('timing-%s-%s-%02d.json' % (cls.__name__, pacing, layer))
    path.write_text(json.dumps(result, indent=2))
    print('COLUMN_COLD_MODEL_PASS', cls.__name__, pacing, layer, last_commit+1, counts['quant_blocked'], flush=True)
    return result


if __name__ == '__main__':
    prefix, commands = observed_program()
    for cls in [Core, ColumnCore, SerialColumnCore]:
        for pacing in ['response_relative', 'conservative_IR']:
            for layer in range(1 if cls is Core else 12):
                path = REPORT/('timing-%s-%s-%02d.json' % (cls.__name__, pacing, layer))
                if not path.exists(): run(cls, pacing, layer, prefix, commands)

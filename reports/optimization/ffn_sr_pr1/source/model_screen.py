"""Compare one parameter-return change against the frozen SR cold task."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'reports/optimization/ffn_sr_pr1'
TRACE = (REPORT / 'received/observation/native-evidence/reports/optimization'
         / 'ffn_sr_pr1/observation/events.csv')
sys.path[:0] = [str(ROOT / 'scripts' / name) for name in
                ('c16_efficiency', 'column_parallel', 'taskflow_study')]
from model import signed, trace_rows
from models import ControlCore, WriteMemory, WriteWrapper
from native_model import cpu_request
from native_simulate import empty_external, idle_cpu

IMAGES = ROOT / 'build/optimization/ffn_ar_area/frozen/images'
START, END = 0xa0020000, 0xa0028800
ANCHORS = dict(cold_cycles=98783, first_mac=29895, last_emit=98754,
               final_physical_commit=98782, final_ack=98784)


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n')


def parameter_read(cmd):
    return cmd['read'] and START <= cmd['address'] < END and cmd['address'] % 4 == 0


class ParameterMemory(WriteMemory):
    def __init__(self, wrapper):
        super().__init__(wrapper)
        self.pending_fast = False
        self.fast_returns = self.fast_turnovers = 0

    def comb(self):
        c = super().comb()
        if self.pending_fast:
            retire = c['rsp_ready']
            handoff = (retire and c['grant'] and c['b']['valid'] and parameter_read(c['b'])
                       and not c['host']['valid'] and not self.host_valid)
            c.update(valid=True, data=self.memory_data, retire=retire,
                     available=handoff, joined_valid=handoff, joined_ready=handoff,
                     ready=handoff, fire=handoff, physical=handoff)
        return c

    def tick(self, command, response_ready, cycle):
        c = self.current
        next_fast = bool(c['fire'] and c['grant'] and parameter_read(c['selected']))
        old_fast = self.pending_fast
        stalled_fast = old_fast and not c['rsp_ready']
        old_q = self.memory_data
        if old_fast:
            # The old response has already been exposed. Do not generate a second one.
            self.pending = 0
            self.current_valid = True
            self.fast_returns += int(not stalled_fast)
            self.fast_turnovers += int(c['fire'])
        super().tick(command, response_ready, cycle)
        if stalled_fast:
            self.valid, self.data = 1, old_q
        self.pending_fast = next_fast


def frozen_image(case):
    number = 2*case + 1
    source = int((IMAGES/'case_sources.hex').read_text().splitlines()[number], 16)
    shared = (IMAGES/('task_%02d_shared.hex' % number)).read_text().splitlines()
    offsets = list(range(3168)) + [16383, 16384+12672, 32767, 32768+8704, 59392+64]
    image = {offset: int(shared[offset], 16) for offset in offsets}
    for start, size, part in ((32768, 8704, 'parameters'), (59392, 64, 'metadata')):
        words = (IMAGES/('linear_layer_%02d_%s.hex' % (source,part))).read_text().splitlines()
        if len(words) != size:
            raise RuntimeError('Frozen image length differs for ' + part)
        image.update((start+i, int(word, 16)) for i, word in enumerate(words))
    expected = [signed(int(word, 16), 16) for word in
                (IMAGES/('task_%02d_expected.hex' % number)).read_text().splitlines()]
    return image, expected

def read_program():
    commands, prefix = [], []
    request = launch_cycle = None
    observed = dict(host_writes=0, descriptors=0, dma_reads=0, dma_writes=0,
                    parameter_accepts=[], parameter_returns=[], parameter_pio_writes=[],
                    final_physical_commit=None, final_ack=None, first_mac=None, last_emit=None)
    outstanding = None
    for row in trace_rows(TRACE):
        cycle = row['cycle']
        if launch_cycle is None:
            prefix.append(row)
            if row['descriptor']:
                launch_cycle = cycle
        elif row['host_cmd_valid'] or row['shared_cpu_cmd_valid']:
            raise RuntimeError('External shared traffic after first descriptor at cycle %d' % cycle)
        if request is None and row['cpu_cmd_valid']:
            request = dict(start=cycle, read=row['cpu_cmd_read'], address=row['cpu_cmd_addr'],
                           data=row['cpu_cmd_wdata'], mask=row['cpu_cmd_wmask'])
        if request is not None and row['cpu_rsp_valid'] and row['cpu_rsp_ready']:
            request['response'] = cycle
            if commands:
                request['gap'] = request['start'] - commands[-1]['response']
            commands.append(request)
            request = None
        if row['host_cmd_valid'] and row['host_cmd_ready'] and not row['host_cmd_read']:
            observed['host_writes'] += 1
        if row['descriptor']:
            observed['descriptors'] += 1
        if row['mem_rsp_valid'] and row['mem_rsp_ready']:
            if outstanding is None:
                raise RuntimeError('DMA response without a command at cycle %d' % cycle)
            reading, address = outstanding
            if reading and START <= address < END:
                observed['parameter_returns'].append([cycle, address, row['mem_rsp_rdata']])
            if not reading and address == 0xa0010000 + 4*12671:
                observed['final_ack'] = cycle
            outstanding = None
        if row['mem_cmd_valid'] and row['mem_cmd_ready']:
            reading, address = row['mem_cmd_read'], row['mem_cmd_addr']
            if outstanding is not None or not row['physical_accept']:
                raise RuntimeError('DMA command lacks sole physical port at cycle %d' % cycle)
            outstanding = reading, address
            observed['dma_reads' if reading else 'dma_writes'] += 1
            if reading and START <= address < END:
                observed['parameter_accepts'].append([cycle, address])
        if row['core_load_valid'] and row['core_load_kind'] == 1:
            observed['parameter_pio_writes'].append([cycle, row['core_load_addr'],
                                                     row['pio_cmd_wdata'], row['private_writes']])
        if row['core_state'] == 7 and observed['first_mac'] is None:
            observed['first_mac'] = cycle
        if row['core_jp_quant_commit']:
            observed['last_emit'] = cycle
        if row['result_write'] and row['physical_write']:
            observed['final_physical_commit'] = cycle
    observed['cold_cycles'] = observed['final_physical_commit'] + 1
    observed['final_ack_source'] = 'event CSV'
    if observed['final_ack'] is None:
        # The testbench clears ld_final_pending at ACK in a separate active-region
        # process. Use the original commit/ACK monitor when the observer misses it.
        receipt = json.loads(TRACE.with_name('result.json').read_text())
        if not receipt['passed'] or receipt['final_physical_commit'] != observed['final_physical_commit']:
            raise RuntimeError('Native commit/ACK receipt does not match the event window')
        observed['final_ack'] = receipt['final_ack']
        observed['final_ack_source'] = 'same-run testbench LOADING_DMA_COUNTS'
    expected = (11946, 102, 11936, 12672, 8704, 8704, 8704)
    actual = tuple(observed[name] for name in ('host_writes', 'descriptors', 'dma_reads', 'dma_writes'))
    actual += tuple(len(observed[name]) for name in ('parameter_accepts', 'parameter_returns',
                                                     'parameter_pio_writes'))
    if actual != expected or any(observed[key] != value for key, value in ANCHORS.items()):
        raise RuntimeError('Native SR observation differs: totals %s, anchors %s' %
                           (actual, {k: observed[k] for k in ANCHORS}))
    image, _ = frozen_image(0)
    macro_counts = {'two': 0, 'zero': 0}
    for index, (request_event, reply, pio) in enumerate(zip(observed['parameter_accepts'],
            observed['parameter_returns'], observed['parameter_pio_writes'])):
        address, data = START + 4*index, image[0x8000+index]
        writes = 2 if index < 8192 or index % 2 == 0 else 0
        if (request_event[1] != address or reply != [request_event[0]+2, address, data] or
                pio[:3] != [reply[0]+1, 2*index, data] or pio[3].bit_count() != writes):
            raise RuntimeError('Observed SR parameter payload/physical write differs at word %d' % index)
        macro_counts['two' if writes == 2 else 'zero'] += 1
    observed['physical_macro_writes_by_word'] = macro_counts
    observed['payload_source'] = 'frozen SR complete-SoC images'
    upcoming = [cmd for cmd in commands if cmd['start'] > launch_cycle]
    if not upcoming or any(cmd['response'] <= launch_cycle for cmd in upcoming):
        raise RuntimeError('Could not extract SR CPU pacing')
    # The first upcoming request follows the already issued launch response.
    previous = commands[commands.index(upcoming[0]) - 1]
    upcoming[0]['gap'] = upcoming[0]['start'] - previous['response']
    return prefix, upcoming, previous['response'], observed


def simulate(variant, pacing, case, prefix, commands, previous_response):
    wrapper = WriteWrapper()
    if variant == 'PR1':
        wrapper.memory = ParameterMemory(wrapper)
    wrapper.core = ControlCore(layer=case)
    memory = wrapper.memory
    image, expected = frozen_image(case)
    for sample in prefix:
        row = dict(sample)
        if row['host_cmd_valid'] and not row['host_cmd_read'] and row['host_cmd_addr'] in image:
            row['host_cmd_wdata'] = image[row['host_cmd_addr']]
        memory.context(row)
        cpu = cpu_request(row)
        c = wrapper.comb(cpu)
        wrapper.tick(cpu, c, row['cycle'])
    index, accepted = 0, False
    due = previous_response + commands[0]['gap']
    retired = 0
    first_mac = last_emit = commit = ack = None
    read_cycles, return_cycles, pio_cycles = [], [], []
    parameter_order = []
    for cycle in range(prefix[-1]['cycle'] + 1, 200000):
        memory.context(empty_external())
        cpu = idle_cpu()
        if index < len(commands) and not accepted and cycle >= due:
            cpu.update({k: commands[index][k] for k in ('read', 'address', 'data', 'mask')})
            cpu['valid'] = 1
        c = wrapper.comb(cpu)
        if cpu['valid'] and c['cpu_ready']:
            accepted = True
        if accepted and c['cpu_valid']:
            accepted = False
            index += 1
            if index < len(commands):
                due = cycle + commands[index]['gap']
                if pacing == 'fixed_cpu':
                    due = max(due, commands[index]['start'])
        if wrapper.core.state == 7 and first_mac is None:
            first_mac = cycle
        if wrapper.core.comb(c['core_in'])['quant']:
            last_emit = cycle
        if c['memory']['valid'] and c['memory']['rsp_ready'] and parameter_order:
            address = parameter_order.pop(0)
            if c['memory']['data'] != image[(address - 0xa0000000) // 4]:
                raise RuntimeError('Parameter response mismatch at %08x' % address)
            return_cycles.append(cycle)
        if c['memory']['fire'] and c['memory']['grant'] and parameter_read(c['memory']['selected']):
            if not c['memory']['physical'] or c['memory']['host_fire'] or parameter_order:
                raise RuntimeError('Parameter read is missing the sole physical port')
            address = c['memory']['selected']['address']
            if address != START + 4 * len(read_cycles):
                raise RuntimeError('Parameter address out of order')
            parameter_order.append(address)
            read_cycles.append(cycle)
        if c['core_in']['load'] and c['core_in']['load_kind'] == 1:
            address = c['core_in']['load_address']
            if address != 2 * len(pio_cycles) or c['command']['data'] != image[0x8000 + address // 2]:
                raise RuntimeError('Private parameter write out of order')
            pio_cycles.append(cycle)
        active = wrapper.engine.pd_active
        for item, value in wrapper.tick(cpu, c, cycle):
            if item != retired or value != expected[item]:
                raise RuntimeError('Ordered output differs at %d' % item)
            retired += 1
        if memory.writes == 12672 and commit is None:
            commit = memory.commits[-1][0]
            for i, (_, address, data) in enumerate(memory.commits):
                packed = (expected[2*i] & 65535) | ((expected[2*i+1] & 65535) << 16)
                if address != 0xa0010000 + 4*i or data != packed:
                    raise RuntimeError('Physical output write differs at index %d' % i)
        if commit is not None and active and not wrapper.engine.pd_active:
            ack = cycle
            break
    totals = (memory.host_writes, memory.reads, memory.writes, wrapper.engine.launches,
              retired, len(read_cycles), len(return_cycles), len(pio_cycles))
    if totals != (11946, 11936, 12672, 102, 25344, 8704, 8704, 8704) or ack is None or ack <= commit:
        raise RuntimeError('Cold totals or final retirement differ: %s' % (totals,))
    return dict(passed=True, variant=variant, pacing=pacing, case=case+1,
                cold_cycles=commit+1, first_mac=first_mac, last_emit=last_emit,
                final_physical_commit=commit, final_ack=ack, host_writes=totals[0],
                dma_reads=totals[1], dma_writes=totals[2], descriptors=totals[3], ordered_outputs=totals[4],
                parameter_read_cycles=read_cycles, parameter_return_cycles=return_cycles,
                parameter_pio_cycles=pio_cycles, fast_returns=getattr(memory,'fast_returns',0),
                fast_turnovers=getattr(memory,'fast_turnovers',0))


def main():
    prefix, commands, previous_response, observed = read_program()
    save('sr-native-anchors.json', observed)
    baseline = simulate('SR', 'response_relative', 0, prefix, commands, previous_response)
    edge_series = [('parameter_read_cycles', 'parameter_accepts'),
                   ('parameter_return_cycles', 'parameter_returns'),
                   ('parameter_pio_cycles', 'parameter_pio_writes')]
    matches = {key: baseline[key] == value for key, value in ANCHORS.items()}
    matches.update((model, baseline[model] == [row[0] for row in observed[native]])
                   for model, native in edge_series)
    save('calibration.json', dict(passed=all(matches.values()), matches=matches, sr=baseline))
    print('PR1_CALIBRATION', matches, flush=True)
    if not all(matches.values()):
        raise RuntimeError('Inspect SR calibration differences before releasing candidate')
    with ProcessPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(simulate, 'PR1', pacing, case, prefix, commands, previous_response)
                 for pacing in ('response_relative', 'fixed_cpu') for case in range(12)]
        results = []
        for task in tasks:
            result = task.result()
            save('model-%s-%02d.json' % (result['pacing'], result['case']), result)
            results.append({key: value for key, value in result.items() if not key.endswith('_cycles') or key == 'cold_cycles'})
            print('PR1_MODEL_CASE', result['pacing'], result['case'], result['cold_cycles'], flush=True)
    reference = json.loads((ROOT / 'reports/submission/ara-SR-release-20261105/completion.json').read_text())
    total = sum(row['cold_cycles'] for row in results if row['pacing'] == 'response_relative')
    record = dict(calibrated=True, functional_passed=True, timing_eligible=total < sum(reference['cycles']),
                  sr_cycles_total=sum(reference['cycles']), candidate_cycles_total=total,
                  candidate_throughput=1800000000/total, results=results,
                  measured_hardware=False, internal_ready_replayed=False)
    save('model-results.json', record)
    print('PR1_MODEL_COMPLETE', record['timing_eligible'], total, flush=True)


if __name__ == '__main__':
    main()

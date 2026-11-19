"""M1/M2 scheduling studies on independently validated transport and core components."""
from pathlib import Path
import gzip
import json
from model import Core, REPORT
from transport import Wrapper


def descriptors():
    jobs = [('input', 0, 64)]
    for pair in range(50):
        if pair < 49:
            jobs.append(('input', (pair + 1) * 64, 32 if pair == 48 else 64))
        jobs.append(('output', pair * 256, 128 if pair == 49 else 256))
    return jobs


def choose(wrapper, name, jobs):
    core, engine = wrapper.core, wrapper.engine
    if engine.pd_active or engine.pd_count or engine.pd_source_pending or engine.pd_dest_pending or wrapper.pack_pending:
        return None
    if name == 'M1':
        if not jobs:
            return None
        kind, index, words = jobs.pop(0)
        return dict(address=(0xa0000000 if kind == 'input' else 0xa0010000) + index * 4,
                    words=words, direction=int(kind == 'output'))
    needed = min((core.row + (1 if core.row == 98 else 2)) * 64, 6336)
    capacity = core.capacity(0)
    if core.input_count < needed and wrapper.memory.reads < 3168 and capacity:
        return dict(address=0xa0000000 + wrapper.memory.reads * 4, words=1, direction=0)
    if len(core.queue.held) == 2 and wrapper.memory.writes < 12672:
        return dict(address=0xa0010000 + wrapper.memory.writes * 4, words=1, direction=1)
    prefetch_limit = min((core.row + 4) * 64, 6336)
    if core.input_count < prefetch_limit and wrapper.memory.reads < 3168 and capacity:
        return dict(address=0xa0000000 + wrapper.memory.reads * 4, words=1, direction=0)
    return None


def study(name):
    core = Core(initial_state=2, numeric=False)
    wrapper = Wrapper(core)
    jobs = descriptors()
    started = False
    last_ack = None
    records = []
    waits = dict(input_missing=0, quantization_blocked=0, dma_busy=0, safe_switch_wait=0)
    events = REPORT / (name + '-events.jsonl.gz')
    with gzip.open(events, 'wt', encoding='utf-8') as stream:
        for cycle in range(1000000):
            cpu = dict(valid=int(not started), address=0x18, read=0, data=1, mask=15, rsp_ready=1)
            c = wrapper.comb(cpu)
            if cpu['valid'] and c['cpu_ready']:
                started = True
            launch = choose(wrapper, name, jobs) if started and core.state != 2 else None
            if launch is not None:
                c['launch'] = launch
                records.append(dict(cycle=cycle, **launch))
            queue = core.queue
            qc = core.comb(c['core_in'])
            event = dict(cycle=cycle, state=core.state, row=core.row, tile=core.tile,
                         inner=core.inner, item=core.item, input_count=core.input_count,
                         input_write=(core.input_count if c['core_in']['load'] and wrapper.load_kind == 0 else None),
                         input_read=(core.inner + 1 if core.state == 7 and core.inner < 63 else 0 if core.state == 6 and core.complete() else None),
                         quant=(dict(row=core.row + core.emit_row, column=core.tile * 8 + core.lane) if qc['quant'] else None),
                         retire=qc['q']['pop_count'], read0=qc['q']['read0'], read1=qc['q']['read1'],
                         issue=qc['q']['issue'], drain0=qc['q']['drain0'],
                         fifo=queue.fifo_count, row0=queue.row0_count, row1=queue.row1_count,
                         held=len(queue.held), pending=len(queue.pending),
                         memory_accept=bool(c['commands']['memory']['valid'] and c['memory']['ready']),
                         memory_read=c['commands']['memory']['read'])
            if (event['input_write'] is not None or event['input_read'] is not None or event['quant'] or event['retire'] or event['read0'] or event['read1'] or event['drain0'] or event['memory_accept'] or cycle % 64 == 0):
                stream.write(json.dumps(event, separators=(',', ':')) + '\n')
            waits['input_missing'] += int(core.state in [6, 15] and not core.complete())
            waits['quantization_blocked'] += int(core.state == 8 and not qc['quant'])
            waits['dma_busy'] += int(bool(wrapper.engine.pd_active))
            busy_before = wrapper.engine.pd_active
            output_before = wrapper.engine.output_transfer
            wrapper.tick(cpu, c, cycle)
            if busy_before and not wrapper.engine.pd_active and output_before:
                last_ack = cycle
            if wrapper.memory.writes == 12672 and not wrapper.engine.pd_active:
                break
        else:
            result = dict(name=name, status='inconclusive', reason='Model progress did not reach the final writeback',
                          cycles=cycle, core=core.snapshot(), engine=wrapper.engine.snapshot())
            (REPORT / (name + '-result.json')).write_text(json.dumps(result, indent=2))
            return result
    result = dict(name=name, status='model_completed', model_window_cycles=cycle + 1,
                  final_physical_commit_cycle=wrapper.memory.commits[-1][0], final_response_cycle=last_ack,
                  outputs_retired=core.queue.retired, outputs_quantized=core.quantized,
                  input_dma_reads=wrapper.memory.reads, output_dma_writes=wrapper.memory.writes,
                  input_output_descriptors=wrapper.engine.launches,
                  parameter_descriptors_before_model_window=2, parameter_dma_reads_before_model_window=8768,
                  queue_peak=core.queue.peak, waits=waits,
                  native_cold_task_cycles=None, native_throughput_tasks_per_second=None,
                  area_mm2=None, power_w=None,
                  timing_scope='Independent accelerator-only model with 3-cycle local responder; host/CPU cold prefix not yet calibrated',
                  arithmetic_scope='Frozen numerical operator; value-independent scheduling uses identity tokens',
                  direction_switch='Only after all pending responses, DMA slots and packed high half retire',
                  issue_cost='One clocked engine launch per segment, no simultaneous launch/old retirement')
    (REPORT / (name + '-result.json')).write_text(json.dumps(result, indent=2))
    (REPORT / (name + '-launches.json')).write_text(json.dumps(records, indent=2))
    return result


if __name__ == '__main__':
    for name in ['M1', 'M2']:
        print(json.dumps(study(name), indent=2), flush=True)

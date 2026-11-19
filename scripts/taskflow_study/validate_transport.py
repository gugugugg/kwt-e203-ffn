"""Validate M0 local control/transport from external command inputs, never ready replay."""
import json
from model import Core, REPORT, trace_rows
from transport import Wrapper


def main():
    wrapper = Wrapper(Core(initial_state=2))
    mismatches, rows, retired = [], 0, 0
    for row in trace_rows(REPORT / 'local-events.csv'):
        rows += 1
        cpu = dict(valid=row['cpu_cmd_valid'], read=row['cpu_cmd_read'], address=row['cpu_cmd_addr'],
                   data=row['cpu_cmd_wdata'], mask=row['cpu_cmd_wmask'], rsp_ready=row['cpu_rsp_ready'])
        c = wrapper.comb(cpu)
        fields = wrapper.core.snapshot()
        fields.update(wrapper.snapshot())
        fields.update(c['snapshot'])
        differences = {k: (int(v), row[k]) for k, v in fields.items() if int(v) != row[k]}
        if c['cpu_valid'] and c['cpu_data'] != row['cpu_rsp_rdata']:
            differences['cpu_rsp_rdata'] = c['cpu_data'], row['cpu_rsp_rdata']
        if c['commands']['memory']['valid']:
            for k, field in [('address', 'mem_cmd_addr'), ('read', 'mem_cmd_read')]:
                if c['commands']['memory'][k] != row[field]:
                    differences[field] = c['commands']['memory'][k], row[field]
            if not c['commands']['memory']['read'] and c['commands']['memory']['data'] != row['mem_cmd_wdata']:
                differences['mem_cmd_wdata'] = c['commands']['memory']['data'], row['mem_cmd_wdata']
        if differences:
            mismatches.append(dict(cycle=row['cycle'], fields=differences))
            break
        retired += len(wrapper.tick(cpu, c, row['cycle']))
    result = dict(passed=not mismatches and retired == 25344, rows_compared=rows, outputs=retired,
                  input_dma_reads=wrapper.memory.reads, output_dma_writes=wrapper.memory.writes,
                  input_output_descriptors=wrapper.engine.launches, mismatches=mismatches,
                  internal_ready_replayed=False, scope='Accelerator-only representative window; parameter descriptors precede this trace',
                  full_native_cold_cpu_timing_validated=False, queue_peak=wrapper.core.queue.peak)
    (REPORT / 'local-M0-validation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

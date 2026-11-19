"""Summarize model intervals with identical layer-start-to-physical-commit endpoints."""
import json
from model import REPORT, trace_rows


def main():
    start = last_commit = last_ack = None
    quant_blocked = 0
    count = 0
    for row in trace_rows(REPORT / 'local-events.csv'):
        count += 1
        if row['core_layer_start']:
            start = row['cycle']
        if row['mem_cmd_valid'] and row['mem_cmd_ready'] and not row['mem_cmd_read']:
            last_commit = row['cycle']
        if row['mem_rsp_valid'] and row['mem_rsp_ready'] and row['dma_output_transfer'] and row['dma_dest_remaining'] == 1:
            last_ack = row['cycle']
        quant_blocked += int(row['state'] == 8 and not row['quant'])
    m0 = dict(name='M0', status='local_cycle_exact', observation_rows=count,
              layer_start_cycle=start, last_physical_commit_cycle=last_commit,
              last_response_cycle=last_ack, comparable_window_cycles=last_commit - start + 1,
              quantization_blocked_cycles=quant_blocked,
              full_cpu_cold_window_calibrated=False,
              scope='Unmodified IR accelerator, 3-cycle local responder; parameters loaded before this observation window')
    rows = [m0]
    for name in ['M1', 'M2']:
        r = json.loads((REPORT / (name + '-result.json')).read_text())
        r['comparable_window_cycles'] = r['final_physical_commit_cycle'] + 1
        r['delta_cycles_vs_local_M0'] = r['comparable_window_cycles'] - m0['comparable_window_cycles']
        r['relative_window_time_change'] = r['delta_cycles_vs_local_M0'] / m0['comparable_window_cycles']
        rows.append(r)
    summary = dict(status='partial_native_observation_deferred_by_user',
                   native_observation_started=False, native_CPU12_or_EDA_repeated=False,
                   models=rows, M3=json.loads((REPORT / 'M3-result.json').read_text()),
                   formal_IR_reference=dict(cycles=148271, throughput_tasks_per_second=1011.661080049369,
                                            scoring_area_mm2=0.221187458, weighted_mean_power_w=0.022464915030806946),
                   native_model_T_P_A_accepted=False,
                   decision='No hardware implementation recommendation yet; restore native calibration and resolve allocation/cost coverage first')
    (REPORT / 'local-model-summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(dict(M0=m0, M1_delta=rows[1]['delta_cycles_vs_local_M0'],
                         M2_delta=rows[2]['delta_cycles_vs_local_M0'],
                         full_native_calibration=False), indent=2))


if __name__ == '__main__':
    main()

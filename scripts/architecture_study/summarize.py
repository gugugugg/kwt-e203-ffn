"""Close three fixed research routes without promoting model PPA to hardware results."""
import json
import numpy as np
from common import ROOT,REPORT,dump


def run():
    numeric=json.loads((REPORT/'numeric-validation.json').read_text(encoding='utf-8'))
    cycles=json.loads((REPORT/'cycle-results.json').read_text(encoding='utf-8'))
    normal=json.loads((REPORT/'normal-scenarios.json').read_text(encoding='utf-8'))
    B=json.loads((REPORT/'B-model-result.json').read_text(encoding='utf-8'))
    cost=json.loads((REPORT/'cost-budget.json').read_text(encoding='utf-8'))
    balance=json.loads((REPORT/'C-perfect-balance-bound.json').read_text(encoding='utf-8'))
    A=next(r for r in cycles['results'] if r['route']=='A')
    C=[r for r in cycles['results'] if r['route']=='C']
    assert numeric['passed'] and normal['passed'] and len(C)==12
    assert all(r['passed'] and r['outputs']==25344 for r in cycles['results'])
    exact_unchanged=(ROOT/'constraints/ffn_selected.json').read_bytes()==(REPORT/'frozen/ffn_selected.json').read_bytes()
    assert exact_unchanged
    summary=dict(status='completed_research_zero_hardware_recommendations',
        baseline=dict(variant='ffn_lp_IR',cycles=148271,throughput=150000000/148271,
                      area_mm2=.221187458,weighted_power_w=.022464915030806946),
        A=dict(status='negative_current_static_4x4_representative',cold_cycles=A['cold_cycles'],
               throughput_prediction=A['case_model_tasks_per_second'],MAC_clocks=102400,
               input_reads=A['counts']['input_reads'],weight_reads=A['counts']['weight_reads'],
               quantization_blocked=A['counts']['quantization_blocked'],IO_macro_count=11,
               added_macro_geometry_um2=cost['A']['added_macro_geometry_um2'],
               pointer='cycles/A-layer-00.json',physical_output_values_checked=25344,
               twelve_case_timing='Inferred data independent at this fixed shape, not twelve new CPU observations',
               interpretation='Half the weight reads, double input reads, unchanged MAC work, more buffering and output blockage. Does not reject other loop/storage organizations.'),
        B=dict(status='inconclusive_under_current_cost_and_timing_evidence',conditional_cycles=148271,
               conditional_throughput=B['conditional_throughput'],exact_outputs=304128,
               mean_digit_coefficients_used_two_rows=float(np.mean([r['B']['mean_reused_table_coefficients_two_rows'] for r in numeric['layers_results']])),
               coefficient_adders=22,new_table_FF_bits=0,selectors_16way_20bit=64,
               mapped_area_delta_um2=None,new_power_w=None,clock_closed=False,
               interpretation='Exactness proven for the representative. A large selector network and same-cycle timing remain unresolved; no measured negative PPA claimed.'),
        C=dict(status='negative_current_16_one_term_lanes_capacity',predicted_cycles_12=[r['cold_cycles'] for r in C],
               mean_cycles=float(np.mean([r['cold_cycles'] for r in C])),
               weighted_12case_throughput_prediction=cycles['route_C_12case_model_throughput'],
               ideally_balanced_same_capacity_throughput_upper_bound=balance['aggregate_12case_throughput_upper_bound'],
               exact_outputs=304128,mask_state_bits=128,
               interpretation='Same one-term-per-lane service capacity misses throughput even with perfect balancing. Does not refute bit-parallel/serial hybrids with different within-clock hardware.'),
        validation=dict(B_C_exact_codes=608256,normal_scenarios=6,normal_frames=12,
                        normal_outputs=12*25344,normal_passed=True,
                        boundary_cases=numeric['boundaries'],A_physical_port_conflicts=0),
        recommendations=[],hardware_plan_started=False,new_RTL=False,new_native_CPU=False,
        new_synthesis_STA_proof_or_power=False,agents_used=False,IR_selected_bytes_unchanged=True,
        acceptance='No new hardware T/A/P accepted. All timing values above are scoped local predictions or conditional equivalence, not formal twelve-case measurements.',
        decision='Retain IR. Do not start a hardware round: A/C fail the defined model throughput; B has not demonstrated an innovation and area/power budget under IR ceilings.')
    dump('results.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k in ['status','A','B','C','validation']},indent=2,ensure_ascii=False))
    return summary


if __name__=='__main__':run()

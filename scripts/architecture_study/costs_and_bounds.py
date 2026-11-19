"""Structural budgets and optimistic scheduling bounds; no power inference."""
import csv
import json
import math
import numpy as np
from common import ROOT,REPORT,arrays,dump


def run():
    source=ROOT/'reports/optimization/ffn_logic_power/diagnosis/ffn_jp_HM2/private_leaf_power.tsv'
    areas={row['ref_name']:float(row['area_um2']) for row in csv.DictReader(source.open(),delimiter='\t')}
    ff,nand=areas['DRNQV0_12TR40'],areas['NAND2V0_12TR40']
    prior=json.loads((ROOT/'reports/optimization/ffn_taskflow_study/cost-budget.json').read_text())
    macro=prior['potentially_removable_upper_bounds_um2']['one_io_macro']
    work=[]
    for layer in range(12):
        x,w,b,sh,expected=arrays(layer)
        pops=np.array([[abs(int(v)).bit_count() for v in row] for row in w],dtype=np.int64)
        terms=int(np.sum(np.count_nonzero(x,axis=0)*pops.sum(axis=1)))
        ideal_cycles=math.ceil(terms/16)
        work.append(dict(layer=layer,effective_term_additions=terms,
                         ideally_balanced_compute_cycles_lower_bound=ideal_cycles,
                         cold_cycles_lower_bound=12113+ideal_cycles,
                         throughput_upper_bound=150000000/(12113+ideal_cycles)))
    total=sum(r['cold_cycles_lower_bound'] for r in work)
    perfect=dict(layers=work,aggregate_12case_throughput_upper_bound=12*150000000/total,
                 resource='Sixteen adders, at most one independently shifted nonzero term per adder per clock; ignores routing, preparation, dependencies, storage, quantization and writeback overhead',
                 interpretation='Even perfect reordering of the same one-term-per-lane capacity cannot achieve 1000. This is not a rejection of BitL or other hardware providing more within-clock term processing.')
    dump('C-perfect-balance-bound.json',perfect)
    # For an ordinary complete four-row group, before the final four-column tile,
    # younger rows each retain 252 results and all 256 inputs remain necessary.
    live=3*252+4*64
    lower=math.ceil((live-16-2)/128)
    bound=dict(assumptions='Same four-row tile-interleaved schedule, strict row-order retirement, no spill/reload/compression, no additional register queue',
               younger_results_live=756,current_inputs_live=256,total_int16_live=live,
               optimistic_existing_FIFO_and_held_credit=18,minimum_128x16_macros=lower,
               current_IR_IO_macros=5,extra_macros_vs_IR=lower-5,
               extra_macro_geometry_um2=(lower-5)*macro,
               interpretation='Storage demand lower bound for this ordering only. It does not prove a total-area lower bound after arbitrary datapath rewrites, nor reject different loop orders.')
    dump('A-storage-bound.json',bound)
    mux_bits=16*4*20*15
    budget=dict(source_cell_geometry=str(source.relative_to(ROOT)),source_usage='Same-library cell geometry only; HM2 activity/power never used as IR power',
        IR=dict(area_mm2=.221187458,weighted_power_w=.022464915030806946,IO_macros=5,MAC_lanes=16),
        A=dict(input_macros=4,output_macros=7,IO_macro_count=11,
               added_macro_geometry_um2=6*macro,
               reference_area_if_other_IR_logic_unchanged_mm2=.221187458+6*macro/1e6,
               deleted_MACs=0,weight_macros_unchanged=16,
               changed_logic_unknown=['four-way rather than two-way weight selection','two more input holds and more buffer pointers','broadcast buffers and timing repair'],
               credit_not_taken='No generic frontend or MAC deletion; dynamic weight-access reduction is not area credit'),
        B=dict(coefficient_generators=2,coefficient_adders_20bit=22,new_table_register_bits=0,
               selectors_16way_20bit=64,unoptimized_bit_mux2_count=mux_bits,
               three_NAND2_mux_geometry_reference_um2=mux_bits*3*nand,
               conditional_top_digit_negators_20bit=16,
               feedback_reduction='Four selected signed/shifted fragments plus original36 feedback per lane, then final CPA',
               removed='Original sixteen fused16x16+36 arithmetic cones; cannot credit the entire MAC hierarchy because accumulator state, seeds, quantization and clocks remain',
               mapped_area_delta_um2=None,
               range_note='The raw mux-tree geometry is an implementation reference before constant/correlation simplification, not a mapped lower bound. Adder mapping, selectors, fanout and timing repair remain unknown.'),
        C=dict(added_weight_mask_bits=128,bare_mask_FF_reference_um2=128*ff,
               removed='Sixteen full multipliers, not the sixteen36-bit feedback registers',
               added=['eight magnitude/mask selectors and priority encoders','sixteen signed shift/negation paths','preparation and group-completion logic'],
               timing_status='Fails throughput even under ideal balanced work bound'),
        state='No route has demonstrated an area and whole-SoC power budget satisfying the IR ceilings',
        new_measured_area_mm2=None,new_measured_power_w=None)
    dump('cost-budget.json',budget)
    with (REPORT/'cost-budget.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream)
        writer.writerow(['route','structure','reference_area_um2','interpretation'])
        writer.writerows([['A','six additional IO macros',6*macro,'Fixed representative; other logic delta unknown'],
                         ['A','three extra macros from lifetime lower bound',(lower-5)*macro,'Only the stated loop/order/storage assumptions'],
                         ['B','raw20-bit selectors via three NAND2 per bit mux',mux_bits*3*nand,'Unoptimized reference, not mapped or a lower bound'],
                         ['C','128 mask FF bits',128*ff,'Masks only; arithmetic and routing excluded']])
    numeric=json.loads((REPORT/'numeric-validation.json').read_text(encoding='utf-8'))
    B=dict(route='B',status='inconclusive_cost_and_timing',exact_outputs=numeric['outputs_per_route'],
           control_dependency='Unmodified IR protocol and cycle sequence; validated arithmetic substitution is combinational and adds no state',
           conditional_12case_cold_cycles=[148271]*12,conditional_throughput=150000000/148271,
           conditions=['The new combinational DAG must close the same SS150MHz clock without extra stages',
                       'Synthesis must establish total area/power at or below IR; neither has been run'],
           actual_accepted_new_T_A_P=False,logical_MAC_lanes=16,coefficient_generation='Eleven 20-bit additions per activation row on every logical MAC clock; shifts, sign correction and all lookup selectors counted in budget',
           timing_and_power_assumed_free=False)
    dump('B-model-result.json',B)
    print(json.dumps(dict(A_added_macro_um2=6*macro,A_minimum_IO_macros=lower,
                         B_raw_mux_geometry_um2=mux_bits*3*nand,
                         C_ideal_balanced_throughput_upper_bound=perfect['aggregate_12case_throughput_upper_bound']),indent=2))


if __name__=='__main__':run()

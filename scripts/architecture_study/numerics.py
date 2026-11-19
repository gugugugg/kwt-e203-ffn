"""Exact outputs and opportunity statistics on the existing twelve tasks."""
import json
import numpy as np
from common import arrays,wrap36,quantize,nibble_products,bit_products,dump,freeze,rne


def boundary_checks():
    a=np.array([-32768,-32767,-16,-8,-1,0,1,8,15,16,32767],dtype=np.int64)
    w=a.copy()
    original=a[:,None]*w[None,:]
    assert np.array_equal(nibble_products(a,w),original)
    assert np.array_equal(bit_products(a,w),original)
    for base in [-(1<<35),(1<<35)-1,0]:
        assert np.array_equal(wrap36(base+nibble_products(a,w)),wrap36(base+original))
        assert np.array_equal(wrap36(base+bit_products(a,w)),wrap36(base+original))
    ties=0
    for shift in range(13,19):
        values=np.array([q*(1<<shift)+r for q in [-32769,-32768,-2,-1,0,1,2,32766,32767]
                         for r in [(1<<(shift-1))-1,1<<(shift-1),(1<<(shift-1))+1]],dtype=np.int64)
        predicted=quantize(values[:,None],np.array([shift]))[:,0]
        assert predicted.tolist()==[rne(int(v),shift) for v in values]
        ties+=len(values)
    return dict(passed=True,signed_product_cases=len(a)*len(w),feedback_seeds=3,RNE_tie_and_saturation_cases=ties,
                minimum_negative_included=True)


def run():
    freeze()
    boundaries=boundary_checks()
    lookup=np.array([i.bit_count() for i in range(65536)],dtype=np.int64)
    results=[]
    for layer in range(12):
        x,w,b,sh,expected=arrays(layer)
        acc_B=np.broadcast_to(wrap36(b),(99,256)).copy()
        acc_C=acc_B.copy()
        for k in range(64):
            acc_B=wrap36(acc_B+nibble_products(x[:,k],w[k]))
            acc_C=wrap36(acc_C+bit_products(x[:,k],w[k]))
        reference=wrap36(x@w+b)
        codes_B,codes_C=quantize(acc_B,sh),quantize(acc_C,sh)
        assert np.array_equal(reference,acc_B) and np.array_equal(reference,acc_C)
        assert np.array_equal(codes_B,expected) and np.array_equal(codes_C,expected)
        groups=w.reshape(64,32,8)
        digits=np.stack([((groups&65535)>>(4*d))&15 for d in range(4)],axis=-1)
        top=digits[:,:,:,-1]
        absdigits=digits.copy()
        absdigits[:,:,:,-1]=np.abs(np.where(top>=8,top-16,top))
        unique=[len(set(map(int,g.reshape(-1)))) for g in absdigits.reshape(-1,8,4)]
        repeated_full=[8-len(set(map(int,g))) for g in groups.reshape(-1,8)]
        pops=lookup[np.abs(w)]
        steps=1+np.maximum(1,pops.reshape(64,32,8).max(axis=2))
        # Fifty two-row groups; the final group has one active row, as in IR.
        minimum_compute_cycles=int(50*steps.sum())
        row=dict(layer=layer,outputs=25344,passed_B=True,passed_C=True,exact36_feedback=True,
                 A_reference_outputs_passed=np.array_equal(quantize(reference,sh),expected),
                 B=dict(mean_unique_abs_digit_coefficients=float(np.mean(unique)),
                        raw_digit_terms_per_two_row_group=64,
                        mean_reused_table_coefficients_two_rows=float(2*np.mean(unique)),
                        full_weight_duplicate_fraction=float(np.sum(repeated_full)/(64*256)),
                        coefficient_generator_adders=22,registered_table_bits=0,
                        note='Functional vectorization over all columns is not hardware reuse: hardware repeats the two-row table for each eight-column tile'),
                 C=dict(mean_weight_magnitude_popcount=float(pops.mean()),max_weight_magnitude_popcount=int(pops.max()),
                        preparation_and_compute_cycles_lower_bound=minimum_compute_cycles,
                        cold_task_cycles_lower_bound=12113+minimum_compute_cycles,
                        throughput_ceiling_tasks_per_second=150000000/(12113+minimum_compute_cycles),
                        weight_only_term_count_12_rows_unused=False,
                        zero_weight_fraction=float(np.mean(w==0)),
                        additional_weight_mask_bits=128),
                 input_zero_fraction=float(np.mean(x==0)),weight_min=int(w.min()),weight_max=int(w.max()))
        results.append(row)
        dump('numeric/layer-%02d.json'%layer,row)
        print('ARCHITECTURE_NUMERIC_PASS',layer,minimum_compute_cycles,flush=True)
    dump('numeric-validation.json',dict(passed=True,layers=12,outputs_per_route=304128,
         total_B_C_checked_outputs=608256,boundaries=boundaries,layers_results=results,
         scope='Exact local arithmetic models and unchanged existing golden codes; no accuracy benchmark rerun, no hardware PPA'))
    return results


if __name__=='__main__':run()

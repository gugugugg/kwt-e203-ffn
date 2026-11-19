"""Summarize existing-vector repetition and distinguish work accounting from energy."""
import json
import numpy as np
from common import arrays,dump,REPORT

results=[]
for layer in range(12):
    x,w,b,sh,e=arrays(layer)
    unique=[len(set(map(int,row))) for row in w]
    groups=w.reshape(64,32,8)
    nibble=((groups&65535)[...,None]>>np.array([0,4,8,12]))&15
    results.append(dict(layer=layer,full_weight_unique_per_256_mean=float(np.mean(unique)),
         full_weight_duplicate_fraction_across_256=float(1-np.sum(unique)/(64*256)),
         zero_nibble_fraction=float(np.mean(nibble==0)),input_min=int(x.min()),input_max=int(x.max()),
         baseline_mean_weight_reuses_per_read=99/50,A_mean_weight_reuses_per_read=99/25,
         baseline_input_macro_reads=202752,A_input_macro_reads=405504,
         baseline_weight_macro_reads=819200,A_weight_macro_reads=409600,
         baseline_active_product_contributions=1622016,A_active_product_contributions=1622016,
         baseline_MAC_clocks=102400,A_MAC_clocks=102400,
         baseline_and_A_padding_lane_slots=102400*16-1622016))
dump('opportunity-summary.json',dict(layers=results,read_savings_are_not_energy=True,
     B_generator_recomputed_at_each_two_row_eight_column_MAC=True,
     scope='Twelve unchanged fixtures; no input selection, no power or official accuracy measurement'))
print(json.dumps(dict(mean_full_weight_duplicate_fraction=float(np.mean([r['full_weight_duplicate_fraction_across_256'] for r in results])),
                     mean_zero_nibble_fraction=float(np.mean([r['zero_nibble_fraction'] for r in results]))),indent=2))

"""Close the fixed model comparisons without labelling predictions as hardware results."""
import json
from prepare import ROOT, REPORT


def main():
    folder=REPORT/'models'
    calibration=json.loads((folder/'native-M0-validation.json').read_text())
    if not calibration['passed'] or calibration['rows_compared']!=148271:
        raise RuntimeError('IR calibration incomplete')
    groups=[]
    for model in ['ColumnCore','SerialColumnCore']:
        for pacing in ['response_relative','conservative_IR']:
            rows=[json.loads((folder/('timing-%s-%s-%02d.json'%(model,pacing,i))).read_text()) for i in range(12)]
            for row in rows:
                if not row['passed'] or (row['outputs'],row['dma_reads'],row['dma_writes'],row['descriptors'],row['host_writes'])!=(25344,11936,12672,102,11946):
                    raise RuntimeError('Cold-model contract differs')
                expected=dict(mac_clocks=51200 if model=='ColumnCore' else 102400,contributions=1622016,
                    input_macro_reads=101376,weight_macro_reads=819200,bias_requests=6400,shift_requests=6400,
                    tiles=800,quant_pairs=12672)
                if any(row['counts'][k]!=v for k,v in expected.items()):raise RuntimeError('Operation ledger differs')
            cycles=sum(row['cold_cycles'] for row in rows)
            groups.append(dict(model=model,pacing=pacing,cycles=[r['cold_cycles'] for r in rows],
                predicted_throughput=12*150000000/cycles,quantization_blocked=[r['counts']['quant_blocked'] for r in rows],
                representative_counts=rows[0]['counts'],queue_peak=rows[0]['queue_peak'],
                energy_break_even_mean_power_w=2.220596944355184e-05/(cycles/(12*150000000)),
                measured_hardware=False))
    result=dict(passed=True,IR_calibration=calibration,comparisons=groups,
        response_relative='Keep each observed CPU request-start gap after the preceding modeled response; DMA wait-register ready is computed from actual modeled engine state.',
        conservative_IR='Same causal gap rule plus each CPU request cannot precede its observed IR absolute start. This is a conservative pacing scenario, not a guaranteed timing bound.',
        loading='Keep the actual11946 physically committed host writes and causal cold prefix; substitute only the authorized layer payload values.',
        serial_control='Model only: same32 states and16-column tile,8+8 physical MAC phases; same input held across both phases. No second RTL or PPA experiment.',
        numeric='All12 layers compare every ordered output and each physical packed write against exact original int64 dot/bias/RNE results; every output64 products and one seed.',
        power_prediction=None,formal_PPA=None)
    (folder/'summary.json').write_text(json.dumps(result,indent=2))
    lines=['# Fixed32MAC timing and port models','','IR M0 reproduces148271 cycles,25344 outputs,102 descriptors and the original finalcommit/ACK order.','',
        '| Model | CPU pacing | Cold cycles per task | Predicted tasks/s | Quantization blocked |','|---|---|---:|---:|---:|']
    for row in groups:
        lines.append('|%s|%s|%d|%.9f|%d|'%(row['model'],row['pacing'],row['cycles'][0],row['predicted_throughput'],row['quantization_blocked'][0]))
    lines+=['','The95479 conditional count does not survive unchanged-wait assumptions: the16-beat EMIT burst interacts with real single-port stash reads/drains and delayed descriptor retirement.',
        'The response-relative32MAC model records5076 quantization waits. FIFO16, row0stash128 and row1stash256 reach their actual limits; ready prevents overwrites and the task drains without deadlock.',
        'Port rules: row0 stash read excludes FIFO drain; row1 pair push excludes stash read. Pending read returns reserve held capacity before another issue. Packed-high input writes drain before direction switching.',
        'The conservative IR pacing holds old CPU issue dates and therefore creates substantially more queue waits. It is an alternative causal driver assumption, not an independently measured CPU speed.',
        'No new hardware throughput, area, average power or energy has been measured. Native CPU instruction timing and real final-netlist PPA remain required.']
    (folder/'summary.md').write_text('\n'.join(lines)+'\n')
    print('COLUMN_MODEL_MATRIX_COMPLETE',flush=True)


if __name__=='__main__':main()

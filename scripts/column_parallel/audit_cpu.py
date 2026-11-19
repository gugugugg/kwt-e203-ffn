"""Audit retained CPU12 logs against the fixed operation/physical-task contract."""
import json
import re
from prepare import ROOT,REPORT


def main():
    folder=REPORT/'received/cpu-accepted/native-evidence/reports/optimization/complete_soc/ffn_cp_C16'
    evaluation=json.loads((folder/'evaluation.json').read_text())
    rows=[]
    for item in evaluation['rows']:
        task=item['tasks'][0];case=task['case']
        text=(folder/('run_%02d.log'%case)).read_text()
        def values(prefix):
            line=next(line for line in text.splitlines() if line.startswith(prefix+' '))
            return {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
        traffic=values('LOADING_DMA_COUNTS');counts=values('LOGIC_POWER_COMPUTE_COUNTS')
        access=values('FFN_NEXT_COUNTS');phase=values('FFN_ROUND3_PHASE')
        required=dict(host_payload=11936,host_setup=5,host_control=5,dma_reads=11936,dma_writes=12672,cpu_output_words=0)
        expected=dict(initial_bias_pairs=8,seed_consumes=799,next_bias_requests=6392,first_requests=799,
            follow_requests=5593,reseed_pairs=12664,shadow_captures=0,push_cycles=12672,push_words=25344,pair_pushes=12672)
        macros=dict(input_reads=101376,weight_reads=819200,bias_reads=25600,shift_reads=6400,
                    stash_reads=25344,stash_writes=25344)
        for observed,wanted in [(traffic,required),(counts,expected),(access,macros)]:
            if any(observed[k]!=v for k,v in wanted.items()):raise RuntimeError('CPU fixed contract differs at case%d'%case)
        if not item['passed'] or task['outputs']!=25344 or task['trace']!=25344:raise RuntimeError('Output/trace failure')
        if traffic['last_commit']!=task['cycles']-1 or traffic['last_ack']<traffic['last_commit']:
            raise RuntimeError('Physical task boundary differs')
        counts['quantization_blocked_cycles']=phase['fifo_blocked']-6272
        rows.append(dict(case=case,task=task,traffic=traffic,compute=counts,macros=access,phase=phase))
    total=sum(r['task']['cycles'] for r in rows)
    if len(rows)!=12:raise RuntimeError('Incomplete CPU12')
    result=dict(passed=True,rows=rows,cycles=[r['task']['cycles'] for r in rows],
        throughput_per_second=12*150000000/total,mean_task_energy_j=None,mean_power_w=None,scoring_area_mm2=None,
        energy_break_even_mean_power_w=2.220596944355184e-05/(total/(12*150000000)),
        native_CPU_measured=True,full_PPA_accepted=False,CPU_SAIF_rerun=False)
    (REPORT/'cpu12-accepted.json').write_text(json.dumps(result,indent=2))
    print('COLUMN_CPU12_CONTRACT_VERIFIED',result['cycles'],result['throughput_per_second'])


if __name__=='__main__':main()

"""Reconcile each independent final measurement, complete acceptance and unchanged W."""
from pathlib import Path
import json
from prepare import ROOT,REPORT,BUILD

def main():
    selection=json.loads((REPORT/'final-selection.json').read_text());results=[]
    for row in selection['candidates']:
        name=row['variant'];profile=json.loads((ROOT/row['profile']).read_text());tag=profile['tag'];folder=ROOT/'reports/optimization/complete_soc'/name
        tasks=sorted([t for p in folder.glob('task_*.json') for t in json.loads(p.read_text())['tasks']],key=lambda t:t['case']);evaluation=json.loads((folder/'power_evaluation.json').read_text());mapped=json.loads((folder/'mapped_evaluation.json').read_text())
        if len(tasks)!=12 or len(evaluation)!=12 or not all(p['completed'] and not p['reused_initial_measurement'] and p['tag']==tag for p in evaluation):raise RuntimeError('Own fresh CPU12/power12 incomplete '+name)
        if not all(row.get(k) for k in ['formal_passed','mapped_passed','rtl_formal_passed','hold_repair_formal_passed','final_repair_formal_passed']):raise RuntimeError('Own acceptance incomplete '+name)
        if len(mapped)!=1 or not mapped[0]['passed'] or mapped[0]['case']!=1:raise RuntimeError('Own representative mapped incomplete')
        observed=mapped[0]['tasks']
        if len(observed)!=1 or observed[0]['outputs']!=25344 or observed[0]['cycles']!=tasks[0]['cycles']:raise RuntimeError('Representative mapped output/cold-cycle boundary differs')
        acknowledgements=mapped[0]['physical_commit_ACK_observation']
        if len(acknowledgements)!=1 or acknowledgements[0]['last_commit']+1!=tasks[0]['cycles'] or acknowledgements[0]['last_ack']<acknowledgements[0]['last_commit']:raise RuntimeError('Representative physical commit/ACK observation differs')
        if not all(t['outputs']==25344 and t['trace']==25344 and t['host_payload']==11936 for t in tasks):raise RuntimeError('Output/trace/cold loading contract differs')
        energy=0.0
        for t in tasks:
            p=json.loads((ROOT/'reports/server'/('complete_soc_sm40_'+tag)/('power_%d'%t['case'])/'power_values.json').read_text())
            if p['unit']!='W':raise RuntimeError('Power unit differs')
            energy+=p['total_w']*t['cycles']/150000000
        cycles=sum(t['cycles'] for t in tasks);measured=dict(mean_energy_j=energy/12,mean_power_w=energy/(cycles/150000000),throughput_per_second=12*150000000/cycles)
        if any(row[k]!=v for k,v in measured.items()):raise RuntimeError('Exact complete-task aggregation differs')
        area=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'];limits=selection['targets']
        objective=measured['mean_energy_j']<limits['energy_strictly_below_j'] and area<=limits['area_at_most_mm2'] and measured['throughput_per_second']>=limits['throughput_at_least']
        if objective!=row['objective_met']:raise RuntimeError('Exact target decision differs')
        results.append(dict(variant=name,tag=tag,passed=True,objective_met=objective,scoring_area_mm2=area,cycles=row['cycles'],**measured))
    if (ROOT/'constraints/ffn_selected.json').read_bytes()!=(BUILD/'frozen/selected-original.json').read_bytes():raise RuntimeError('Published C changed')
    v=dict(passed=True,candidates=results,published_variant='ffn_wen_C',publication_changed=False,all_own_fresh_power12=True,all_three_proofs=True,all_representative_mapped=True,mapped_ordered_trace=False)
    (REPORT/'final-acceptance-audit.json').write_text(json.dumps(v,indent=2));print(json.dumps(v,indent=2))

if __name__=='__main__':main()

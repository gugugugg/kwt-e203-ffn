"""Report actual area/energy tradeoffs and separable state without rerunning references."""
import csv,json,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from ffn_c_area import REPORT,dump

def components(row):
    folder=ROOT/'reports/optimization/complete_soc'/row['variant'];tag=json.loads((ROOT/row['profile']).read_text())['tag'];tasks=[t for p in folder.glob('task_*.json') for t in json.loads(p.read_text())['tasks']]
    energy={};counts={};unknown=[]
    for task in tasks:
        path=ROOT/'reports/server'/('complete_soc_sm40_'+tag)/('power_%d'%task['case'])/'c_area_state_cells.tsv'
        if not path.exists():unknown.append(dict(case=task['case'],reason='Historical reference has no new state-cell export; do not rerun it'));continue
        roles=Counter()
        with path.open() as stream:
            for c in csv.DictReader(stream,delimiter='\t'):
                role=c['role'];roles[role]+=1
                if c['total_w']=='NA':unknown.append(dict(case=task['case'],cell=c['cell'],value='NA'));continue
                energy[role]=energy.get(role,0)+float(c['total_w'])*task['cycles']/150000000/12
        counts[str(task['case'])]=dict(roles)
    return dict(mean_energy_j=energy,counts=counts,unknown=unknown,other_or_unseparated_energy_j=row['mean_energy_j']-sum(energy.values()))

def main():
    s=json.loads((REPORT/'final-selection.json').read_text());base=s['baseline'];rows=[base,s['accepted_SS_reference']]+s['candidates'];out=[]
    with (REPORT/'library/cells.tsv').open() as stream:lib_area={r['ref']:float(r['area_um2']) for r in csv.DictReader(stream,delimiter='\t')}
    with (REPORT/'library/pins.tsv').open() as stream:lib_ck={r['ref']:float(r['capacitance']) for r in csv.DictReader(stream,delimiter='\t') if r['pin'].endswith('/CK')}
    for row in rows:
        area=row['metrics']['area']['accelerator_budget_including_shared_interface_mm2']
        v=dict(variant=row['variant'],cycles=row['cycles'],throughput_per_second=row['throughput_per_second'],mean_energy_j=row['mean_energy_j'],mean_power_w=row['mean_power_w'],scoring_area_mm2=area,delta_area_um2=(area-base['metrics']['area']['accelerator_budget_including_shared_interface_mm2'])*1e6,delta_energy_j=row['mean_energy_j']-base['mean_energy_j'],module_mean_energy_j=row['module_mean_energy_j'],state_components=components(row))
        dt=8*(row['throughput_per_second']-base['throughput_per_second']);de=8*(1/row['mean_energy_j']-1/base['mean_energy_j']);da=4*(1/area-1/base['metrics']['area']['accelerator_budget_including_shared_interface_mm2'])
        v['score_break_even_vs_C']=dict(inverse_Tmax_coefficient=dt,Emin_j_coefficient=de,Amin_mm2_coefficient=da,condition='dt/Tmax + de*Emin + da*Amin > 0 before official caps and rounding; use one shared recomputed qualified cohort',opponent_references_available=False)
        if dt==0 and da>0 and de<0:v['score_break_even_vs_C']['required_Amin_over_Emin_mm2_per_j']=-de/da
        inv=REPORT/'activity-mapping/native-review-first'/row['variant']/'inventory.json'
        if row['variant']=='ffn_wen_C':inv=ROOT/'reports/optimization/ffn_w_energy/activity-mapping/native-review-first/ffn_wen_C/inventory.json'
        elif row['variant']=='ffn_cfe_SS':inv=ROOT/'reports/optimization/ffn_c_final_energy/activity-mapping/native-review-first/ffn_cfe_SS/inventory.json'
        if inv.exists():
            data=json.loads(inv.read_text());profile=json.loads((ROOT/row['profile']).read_text())
            if data['tag']!=profile['tag']:raise RuntimeError('Read the exact accepted inventory tag '+row['variant'])
            cells=data['cells'];acc={k:c for k,c in cells.items() if '/core/accumulator_reg_' in k};refs=Counter(c['ref'] for c in acc.values())
            v['actual_accumulator']=dict(cells=len(acc),refs=dict(refs),reset_pins=sum(any(x in c['pins'] for x in ['RDN','SDN','RN','SN']) for c in acc.values()),bare_FF_area_um2=sum(n*lib_area[r] for r,n in refs.items()) if all(r in lib_area for r in refs) else None,library_CK_pin_capacitance_sum_pF=sum(n*lib_ck[r] for r,n in refs.items()) if all(r in lib_ck for r in refs) else None,inventory_source=inv.relative_to(ROOT).as_posix(),tag=data['tag'])
            v['actual_destination_remaining_FFs']=sum('/dma_frontend/loading_dma/dest_remaining_reg_' in k for k in cells)
            state_refs=Counter(c['ref'] for k,c in cells.items() if '/core/accumulator_reg_' in k or '/dma_frontend/loading_dma/' in k and any('/'+stem+'_reg_' in k for stem in ['source_remaining','dest_remaining','pd_count']))
            v['accumulator_and_remaining_state_bare_FF_area_um2']=sum(n*lib_area[r] for r,n in state_refs.items()) if all(r in lib_area for r in state_refs) else None
        out.append(v)
    for v in out:
        if v.get('accumulator_and_remaining_state_bare_FF_area_um2') is not None and out[0].get('accumulator_and_remaining_state_bare_FF_area_um2') is not None:
            v['actual_bare_state_FF_area_delta_um2']=v['accumulator_and_remaining_state_bare_FF_area_um2']-out[0]['accumulator_and_remaining_state_bare_FF_area_um2']
            v['other_scoring_structure_area_delta_um2']=v['delta_area_um2']-v['actual_bare_state_FF_area_delta_um2']
    result=dict(versions=out,target_met=s['target_met'],preferred_recommendation=s['recommended_area_candidate'],pareto_candidates=s['pareto_candidates'],baseline_and_SS_not_rerun=True,zero_filled=False,publication_changed=False,official_score=None)
    dump(REPORT/'cost-attribution.json',result)
    lines=['# C面积优化实测与结构成本','','|配置|tasks/s|任务能耗μJ|平均功率mW|计分面积mm²|相对C面积μm²|相对C能耗nJ|','|---|---:|---:|---:|---:|---:|---:|']
    for v in out:lines.append('|%s|%.12f|%.12f|%.12f|%.9f|%+.6f|%+.9f|'%(v['variant'],v['throughput_per_second'],v['mean_energy_j']*1e6,v['mean_power_w']*1e3,v['scoring_area_mm2'],v['delta_area_um2'],v['delta_energy_j']*1e9))
    lines+=['','面积且能耗不增优先；增耗取舍保留，不设百分比阈值。Pareto集合：'+', '.join(s['pareto_candidates'])+'。发布C与W/C16/IR回退保持。','','条件裸FF预算1470.8736μm²及D1的214.5024μm²不是实际净面积；最终数据包括实际推断单元、ICG、复位分发、反馈选择、缓冲与全部时序修复。','']
    for v in out:
        lines+=['## '+v['variant'],'','|可分离状态角色|nJ/任务|','|---|---:|']
        for role,e in v['state_components']['mean_energy_j'].items():lines.append('|%s|%.9f|'%(role,e*1e9))
        lines+=['|其余或未分离区域|%.9f|'%(v['state_components']['other_or_unseparated_energy_j']*1e9),'']
        if 'actual_accumulator' in v:lines.append('实际累加状态：'+json.dumps(v['actual_accumulator'])+'；目的剩余FF数量：'+str(v['actual_destination_remaining_FFs'])+'。')
        if 'actual_bare_state_FF_area_delta_um2' in v:lines.append('实际累加器及source/dest/pending计数裸FF面积相对C变化%+.6fμm²；其余计分结构净变化%+.6fμm²。其余项包含反馈选择、门控、缓冲、其他逻辑和共享接口，不单独归因为reset或计数递减器。'%(v['actual_bare_state_FF_area_delta_um2'],v['other_scoring_structure_area_delta_um2']))
        trade=v['score_break_even_vs_C']
        if 'required_Amin_over_Emin_mm2_per_j' in trade:lines.append('同吞吐下，该面积/增耗取舍相对C的未封顶、未舍入效率分盈亏条件为 Amin/Emin > %.12g mm²/J；实际参照须来自同组共同合格集合，替换后重算。'%trade['required_Amin_over_Emin_mm2_per_j'])
    lines+=['','旧C/SS没有本轮新增状态单元导出，缺失留真；可使用两者已有整机/模块分组比较，不能以新增FF局部值倒扣历史整机。未分离逻辑不全部归为乘法器、reset或目的计数减法器。','缺少共同同组参考时不编造正式分，按8T/Tmax+8Emin/E+4Amin/A给盈亏条件；加入新候选须共同更新参照并应用正式封顶和舍入。','']
    (REPORT/'cost-attribution.md').write_text('\n'.join(lines),encoding='utf8')
    dump(REPORT/'version-parameters.json',dict(experiment='ffn_c_area',numerical_model='Q2/int16 effective36 exact RNE/saturation',MACs=32,clock_hz=150000000,corner='SS .99V125C OCV EMA2',cold_task='11936payload+5guard+5control through last physical SRAM write commit; ACK separate',versions=out,published_variant='ffn_wen_C',fallbacks=['ffn_ce_W','ffn_cp_C16','ffn_lp_IR']))
    print('C_AREA_COST_ATTRIBUTION_WRITTEN',s['target_met'],s['pareto_candidates'],flush=True)

if __name__=='__main__':main()

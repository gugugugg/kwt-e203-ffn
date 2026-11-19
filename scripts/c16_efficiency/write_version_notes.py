"""Record the measured efficiency version while retaining C16 publication."""
import json
from pathlib import Path
from prepare import ROOT,REPORT

def main():
    selection=json.loads((REPORT/'final-selection.json').read_text())
    audit=json.loads((REPORT/'final-acceptance-audit.json').read_text())
    row=selection['candidate'];baseline=selection['baseline']
    value=dict(version='C16 efficiency W',variant='ffn_ce_W',parent='ffn_cp_C16',published_variant='ffn_cp_C16',
        publication_changed=False,hardware_candidates=['ffn_ce_W'],unimplemented_model='C',
        mechanism='Same-DMA same-direction write-response retirement handoff; original read handoff retained',
        numerical=dict(format='Q2/int16',effective_accumulator_bits=36,rounding='exact RNE with saturation',MACs=32,rows=2,columns=16),
        platform=dict(frequency_hz=150000000,corner='SS 0.99V 125C, frozen OCV/EMA2',shared_SRAM_bytes=524288,physical_ports=1),
        cold_boundary='First necessary host parameter/input loading through final physical shared-SRAM write commit; ACK separate',
        per_task=dict(payload=11936,guards=5,controls=5,DMA_reads=11936,DMA_writes=12672,descriptors=102,outputs=25344,products_per_output=64,bias_per_output=1),
        measurement=dict(cycles=row['cycles'],throughput_tasks_per_s=row['throughput_per_second'],mean_power_w=row['mean_power_w'],
                         mean_energy_j=row['mean_energy_j'],area_mm2=audit['area_mm2'],tag=audit['tag']),
        baseline=dict(cycles=baseline['cycles'],mean_energy_j=baseline['mean_energy_j'],mean_power_w=baseline['mean_power_w'],
                      throughput_tasks_per_s=baseline['throughput_per_second'],area_mm2=baseline['metrics']['area']['accelerator_budget_including_shared_interface_mm2']),
        objective=selection['targets'],objective_met=selection['target_met'],relative_to_C16_percent=audit['relative_to_C16_percent'],
        acceptance=dict(CPU12=True,RTL_scenarios=3,fresh_native_power12=True,three_proofs=True,official_SS150_gating_electrical=True,
                        representative_real_CPU_mapped=True,mapped_ordered_trace=False),
        resource_settings=json.loads((ROOT/'constraints/ffn_parallel.json').read_text()),
        evidence_directory=REPORT.relative_to(ROOT).as_posix())
    (REPORT/'version-parameters.json').write_text(json.dumps(value,indent=2))
    lines=['# C16效率W版本参数','',
        '发布配置保持ffn_cp_C16；本版本为独立完整验收的效率研究候选。','',
        '|指标|测量值|','|---|---:|',
        '|周期/任务|%s|'%str(row['cycles']),
        '|吞吐tasks/s|%.12f|'%row['throughput_per_second'],
        '|平均功率mW|%.12f|'%(row['mean_power_w']*1000),
        '|平均任务能耗μJ|%.12f|'%(row['mean_energy_j']*1e6),
        '|计分面积mm²|%.9f|'%audit['area_mm2'],'',
        '本轮目标达成：%s。'%selection['target_met'],
        '数值保持Q2/int16、有效36位和精确RNE/饱和；32MAC、150MHz、冻结SS/OCV/EMA2。',
        '完整冷任务包含必要装载、全部等待与最终物理SRAM写提交。25344项输出有序trace来自RTL及真实CPU；mapped trace=0。',
        'C16与IR成功阶段均未重跑；本候选自身CPU12、SAIF、映射、时序、电气、三证明、功耗12及代表mapped独立验收。']
    (REPORT/'version-parameters.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('EFFICIENCY_VERSION_PARAMETERS_WRITTEN',row['variant'],flush=True)

if __name__=='__main__':main()

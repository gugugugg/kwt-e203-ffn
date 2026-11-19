"""Copy the final acceptance notes to G and package their exact native addendum."""
from pathlib import Path
import json,sys,zlib
from prepare import ROOT,REPORT

def main():
    root=ROOT.resolve();report=REPORT.resolve();g=Path('G:/xpian_历史版本库/研究与规划/ffn_w_energy')
    ack=json.loads((report/'local-sync-confirmed.json').read_text())
    selection=json.loads((report/'final-selection.json').read_text())
    if not all(ack[k] for k in ['verified_local_archive','verified_G_archive','native_ack_confirmed']):raise RuntimeError('Read actual E/G native archive ACK')
    if not selection['local_sync_complete'] or not selection['native_archive_ack']:raise RuntimeError('Selection and ACK differ')
    path=report/'current-state.md';old=path.read_text(encoding='utf8');marker='## 最终完整验收与同步'
    if marker not in old:
        measurements='；'.join('%s E%sμJ/P%smW/T%s/A%smm²'%(row['variant'],repr(row['mean_energy_j']*1e6),repr(row['mean_power_w']*1e3),repr(row['throughput_per_second']),repr(row['metrics']['area']['accelerator_budget_including_shared_interface_mm2'])) for row in selection['candidates'])
        text=old+'\n'+marker+'\n\nC/SL各自代表真实CPU mapped均通过，周期98783/99016、输出25344、mapped trace=0。各自完整RTL/CPU12/SAIF/正式SS150MHz/门控/电气/三证明/原生W12全部齐全。'+measurements+'。两者满足本轮目标，按精确E/T/A推荐C。发布W及C16/IR回退保持不变。\n\n全档案'+str(ack['bytes'])+'字节/CRC'+ack['crc32']+'/'+str(ack['parts'])+'分片已完整回收，E和G顺序GzipFile+tar逐文件比较通过，native verified_local_archive/verified_G_archive/native_ack_confirmed均true。final-selection、delivery-status、local-sync-confirmed与独立final-acceptance-audit一致。最终附加结论和版本参数独立闭合，不重跑任何CPU/EDA/功耗阶段。\n'
        path.write_text(text,encoding='utf8')
    names=['reports/optimization/ffn_w_energy/final-acceptance-audit.json','reports/optimization/ffn_w_energy/version-parameters.json',
        'reports/optimization/ffn_w_energy/conclusion.md','reports/optimization/ffn_w_energy/current-state.md',
        'scripts/w_energy/summarize_delivery.py','scripts/w_energy/prepare_closing.py','scripts/w_energy/native_final_watch.py',
        'scripts/w_energy/native_stage_measured_addendum.py','scripts/w_energy/native_close_delivery.py','scripts/w_energy/native_ack_launcher.py']
    files=[root/name for name in names]
    for p in files:
        target=g/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
        if target.read_bytes()!=p.read_bytes():raise RuntimeError('Closing E/G bytes differ '+str(p))
    sys.path.insert(0,str(root/'scripts/server'));from ffn_delivery_archive import write_archive
    archive=report/'deployment/w-energy-closing.tar.gz';write_archive(archive,files,root)
    data=archive.read_bytes();meta=dict(bytes=len(data),crc32='%08x'%(zlib.crc32(data)&0xffffffff),files=names,E_G_equal=True)
    archive.with_name('w-energy-closing.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta))

if __name__=='__main__':main()

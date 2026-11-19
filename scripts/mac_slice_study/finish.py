import gzip
import json
import struct
import tarfile
import zlib
from datetime import datetime,timezone,timedelta
from prepare import ROOT,REPORT

packet=(ROOT/'reports/remote_vnc/delivery-spool/XSPEED1!/c128b3f1-2307-1-000000.packet').read_bytes()
magic,index,count,total,crc=struct.unpack('<8sIIII',packet[:24]);data=packet[24:]
assert magic==b'XSPEED1!' and index==0 and count==1 and total==2307 and crc==0xc128b3f1
assert len(data)==total and zlib.crc32(data)&0xffffffff==crc
archive=REPORT/'native-final-footer.tar.gz';archive.write_bytes(data)
dest=REPORT/'footer-evidence';dest.mkdir(exist_ok=True)
with archive.open('rb') as raw,gzip.GzipFile(fileobj=raw,mode='rb') as stream,tarfile.open(fileobj=stream,mode='r|') as tar:
    for m in tar:
        if m.isfile():
            content=tar.extractfile(m).read();p=dest/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
            assert p.read_bytes()==content
native=dest/'reports/optimization/ffn_mac_slice_study'
receipt=json.loads((native/'native-final-receipt.json').read_text(encoding='utf-8'))
assert receipt['verified_local_archive'] and receipt['native_archive_members_equal']==124
assert receipt['frozen_IR_inputs_equal']==188 and receipt['selected_unchanged'] and not receipt['actual_EDA_jobs']
assert all(receipt['mapped_equivalence_passed'].values())
(REPORT/'native-final-receipt.json').write_bytes((native/'native-final-receipt.json').read_bytes())
result=json.loads((REPORT/'results.json').read_text())
completion=dict(complete=True,study='ffn_mac_slice_study',variants=['REF','SHARE4'],recommended_SoC_candidates=[],
    exact_arithmetic=True,normal_tasks=36,normal_ordered_outputs=912384,mapped_equivalence=True,
    native_SoC_CPU_run=False,power_measured=False,new_SoC_PPA=None,published_variant='ffn_lp_IR',release_unchanged=True,
    native_verified_local_archive=True,native_archive_bytes=7859244,native_archive_crc32='5ed58ba3',
    G_directory='G:/xpian_历史版本库/研究与规划/ffn_mac_slice_study_20261103',
    final_byte_verification='local-sync.json',timestamp=datetime.now(timezone(timedelta(hours=8))).isoformat())
(REPORT/'completion.json').write_text(json.dumps(completion,indent=2,ensure_ascii=False),encoding='utf-8')
(REPORT/'current-state.md').write_text('''# MAC切片筛选：已完成

REF/SHARE4两个固定配置的实施、精确验证、DC/PT、各自映射FM及E/G证据同步已完成。主代理独立实施，没有子代理、没有新E203 CPU、没有SoC或IR发布变更。

主报告final-report.md、精确指标results.json、完成回执completion.json和local-sync.json。SHARE4切片40999.963079 μm²，对照REF32845.041795 μm²，增加24.8284698034436%；两独立切片150MHz setup均负，REF−0.431440830ns、SHARE4−1.295047045ns。保持、门控及电气报告完整，未报告电气违反。按计划前提没有进入功耗比较；无新整机T/A/P，不推荐后续SoC候选。

REF是IR源码独立重综合，不是IR已验收物理网表。共同切片边界不等同于实际SoC逐pin集成条件，不能据此推翻原IR150MHz验收或宣称方法全局不可能。没有加流水、降频、参数扫描或额外硬件配置。

64个片段符号证明加任意180位压缩/反馈SAT证明闭合，覆盖任意signed16输入、权重及36位反馈。原生额外整bank RTL→RTL FM在组合证明完成后作为冗余停止，原−15/未pass日志保留；不把它冒称成功。两配置各自新的SVF/网表FM分别真正通过。三正常场景各12任务共912384项有序输出，逐拍16路状态和量化与未改IR一致，Icarus actual12也自然通过。

原生源包、raw实现、DDC/SVF/netlist、DC/PT/FM实际脚本及成功/失败日志已回收。native-slice-results.tar.gz7859244B/CRC5ed58ba3/9片完整，顺序GzipFile/tar逐文件核对124成员；native-final-footer.tar.gz2307B/CRCc128b3f1/1片补齐实际GTK失败、legacy python回传成功日志和native-final-receipt。后者verified_local_archive=true、188冻结IR输入一致、selected未变、actual_EDA_jobs=[]。原生控制器249943和恢复helper258156及所有对应EDA均已结束，不再恢复或重跑成功阶段。

G目录G:\\xpian_历史版本库\\研究与规划\\ffn_mac_slice_study_20261103，最终文件数/字节数以local-sync.json为准。逐文件字节核对，不做SHA或清理历史。当前IR仍为发布/提交首选，本阶段结束不自动开启SoC实验或下一轮配置。

通信仅原18791以太网物理路径、认证RFB及唯一reader，健康服务不重启。今后仅在新用户任务需要时使用，不另开reader；传输中只读本机spool。
''',encoding='utf-8')
print('MAC_SLICE_STUDY_COMPLETED_NATIVE_ACK',flush=True)

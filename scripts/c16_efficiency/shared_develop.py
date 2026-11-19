"""Normal shared-port competition and connected real DMA checks for selected W."""
import json
import subprocess
from prepare import ROOT,BUILD,REPORT,selection,write_transform


def main():
    if selection()!='W':return
    out=BUILD/'development/shared';out.mkdir(parents=True,exist_ok=True)
    report=REPORT/'development/shared';report.mkdir(parents=True,exist_ok=True)
    shared=out/'kwt_shared_dma_icb_sm40.sv'
    shared.write_text(write_transform((ROOT/'build/optimization/complete_soc/ffn_cp_C16/kwt_shared_dma_icb_sm40.sv').read_text()))
    bench=(ROOT/'tb/ffn_tile_pipeline/shared_pipeline_tb.sv').read_text()
    bench=bench.replace('!dut.read_pending||!dut.joined_cmd_read||','(dut.read_pending!=dut.joined_cmd_read)||')
    bench=bench.replace('Handoff was not a retiring DMA read followed by a qualified DMA read','Handoff crossed owner/direction or host/pending exclusion')
    (out/'shared_pipeline_tb.sv').write_text(bench)
    engine=(ROOT/'tb/ffn_tile_pipeline/shared_engine_tb.sv').read_text()
    engine=engine.replace('integer mode=0,cycle=0','integer write_handoffs=0;\n    integer mode=0,cycle=0')
    engine=engine.replace('cycle<=cycle+1;',
        'cycle<=cycle+1;\n        if(shared.joined_fire&&shared.joined_rsp_valid&&shared.joined_rsp_ready&&!shared.joined_cmd_read)begin\n'
        '            if(!shared.memory_arbiter.owner||shared.read_pending||shared.pending||hv||hrv)$fatal(1,"WRITE_HANDOFF_QUALIFICATION");\n'
        '            write_handoffs<=write_handoffs+1;\n        end')
    engine=engine.replace('if(EXPECT_RH&&turnover==0)', 'if(write_handoffs==0)$fatal(1,"No same-DMA write response turnover");\n        $display("EFFICIENCY_WRITE_HANDOFFS %0d",write_handoffs);\n        if(EXPECT_RH&&turnover==0)')
    (out/'shared_engine_tb.sv').write_text(engine)
    checks=[]
    for label,tb,extra in [('competition','shared_pipeline_tb',[]),('real-engine','shared_engine_tb',[
            ROOT/'build/optimization/rtl_sources/ffn_ce_W/encoder/kwt_ld_engine.sv',
            ROOT/'tb/ffn_post_dma/transport_engine_tb.sv'])]:
        binary=out/(label+'.vvp')
        commands=[['iverilog','-g2012','-s',tb,'-P'+tb+'.EXPECT_RH=1','-o',binary,shared,
            ROOT/'build/optimization/rtl_sources/ffn_ce_W/encoder/kwt_ld_icb_arbiter.sv',
            ROOT/'tb/ffn_loading_dma/shared_memory_model.sv']+extra+[out/(tb+'.sv')],['vvp',binary]]
        for phase,cmd in zip(['compile','run'],commands):
            with (report/(label+'-'+phase+'.log')).open('w') as log:
                subprocess.run([str(x) for x in cmd],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
            checks.append(dict(scenario=label,phase=phase,passed=True))
    cmd=['yosys','-Q','-T','-p','read_verilog -lib -sv rtl/public_encoder/kwt_shared_sram_sm40.sv; '
         'read_verilog -sv '+shared.relative_to(ROOT).as_posix()+'; hierarchy -top kwt_shared_icb_sm40; proc; flatten; opt; scc -expect 0']
    with (report/'combinational-dependencies.log').open('w') as log:
        subprocess.run(cmd,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    (report/'acceptance.json').write_text(json.dumps(dict(passed=True,checks=checks,combinational_scc=0,
        scope='Normal CPU/DMA/host masks, response backpressure, SRAM hold and unchanged real DMA engine'),indent=2))
    print('EFFICIENCY_SHARED_DEVELOPMENT_PASS',flush=True)


if __name__=='__main__':main()

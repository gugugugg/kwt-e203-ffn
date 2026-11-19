"""Check the selected endpoint and the real two-slot engine with native transaction sizes."""
import json
from pathlib import Path
import subprocess
from candidate import ROOT, REPORT, OUT, ENDPOINT, PRIVATE, NAME, replace

def run(args, log):
    with log.open('w') as stream:
        subprocess.check_call([str(x) for x in args], cwd=str(ROOT), stdout=stream, stderr=subprocess.STDOUT)

def main():
    winner=json.loads((REPORT/'model-selection.json').read_text())['winner']
    work=OUT/'local'
    work.mkdir(exist_ok=True)
    tb=ROOT/'tb'
    shared=OUT/ENDPOINT
    engine=ROOT/'build/optimization/rtl_sources'/NAME/PRIVATE
    memory=tb/'ffn_loading_dma/shared_memory_model.sv'
    engine_tb=(tb/'ffn_tile_pipeline/shared_engine_tb.sv').read_text()
    engine_tb=replace(engine_tb, 'integer mode=0,cycle=0', '''integer first_req=-1, last_req=-1, last_ack=-1;
    integer mode=0,cycle=0''')
    engine_tb=replace(engine_tb, 'if(clear) begin reads<=0;writes<=0;responses<=0;end',
        'if(clear) begin reads<=0;writes<=0;responses<=0;first_req<=-1;last_req<=-1;last_ack<=-1;end')
    engine_tb=replace(engine_tb,'            if(mv&&mr) begin','''            if(engine.pd_count>2) $fatal(1,"Two-slot invariant");
            if(mv&&mr) begin
                if(first_req<0) first_req<=cycle;
                last_req<=cycle;''')
    engine_tb=replace(engine_tb,'if(mrv&&mrr) responses<=responses+1;',
        'if(mrv&&mrr) begin responses<=responses+1;last_ack<=cycle;end')
    engine_tb=replace(engine_tb,'clear=1;direction=output_dir;mode=profile;',
        "clear=1;direction=output_dir;mode=profile;start_address=output_dir?32'ha0010000:32'ha0020000;")
    checks=[]
    if 'PRF' in winner:
        checks.append('if(!output_dir&&profile==0&&words==8704&&(last_req-first_req!=8703||last_ack-last_req!=1)) $fatal(1,"PRF one word per clock");')
    if 'W1' in winner:
        checks.append('if(output_dir&&last_ack-last_req!=1) $fatal(1,"W1 ACK after actual write");')
    engine_tb=replace(engine_tb,'            transfers=transfers+1;',
        '            '+'\n            '.join(checks)+'\n            $display("TRANSPORT_TRANSFER words=%0d write=%0d req_span=%0d ack_delay=%0d",words,output_dir,last_req-first_req,last_ack-last_req);\n            transfers=transfers+1;')
    connected=REPORT/'shared_engine_tb.sv'
    connected.write_text(engine_tb)
    plan=[('engine','shared_engine_tb',[engine,tb/'ffn_post_dma/transport_engine_tb.sv',connected])]
    if 'PRF' in winner:
        plan.append(('endpoint','pr1_endpoint_tb',[ROOT/'scripts/sr_pr1/pr1_endpoint_tb.sv']))
    for label,top,paths in plan:
        vvp=work/(label+'.vvp')
        run(['iverilog','-g2012','-s',top,'-o',vvp,shared,memory]+paths,REPORT/(label+'-compile.log'))
        run(['vvp',vvp],REPORT/(label+'-run.log'))
    run(['iverilog','-g2012','-i','-s','kwt_encoder','-o',work/'core.vvp',
         OUT/'preserved_sr_core.v'],REPORT/'preserved-core-elaborate.log')
    (REPORT/'local-acceptance.json').write_text(json.dumps(dict(passed=True,variant=NAME,
         winner=winner,completed=[label for label,_,_ in plan],preserved_core_elaboration=True),indent=2)+'\n')

if __name__=='__main__':
    main()

"""Prepare the actual mapped bench now, without compiling or running a CPU task."""
import ast,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'scripts/server'),str(ROOT/'scripts')]
from loading_dma_gate_observers import adapt_compile_script

def main():
    tree=ast.parse((ROOT/'scripts/server/check_ffn_c_final_energy_mapped.py').read_text())
    assigned=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='debug_adaptation' for x in n.targets)]
    addition=ast.literal_eval(assigned[0].value);records=[]
    for name in ['ffn_cfe_SS','ffn_cfe_O1']:
        report=ROOT/'reports/optimization/ffn_c_final_energy';state=json.loads((report/(name+'.json')).read_text());tag=json.loads((ROOT/state['profile']).read_text())['tag']
        source=adapt_compile_script((ROOT/'scripts/server/compile_complete_gate.sh').read_text());marker="Path('build/complete_soc/gate_tb.sv').write_text(tb)"
        source=source.replace(marker,addition+'\n'+marker).replace('build/complete_soc','build/optimization/complete_soc/'+name).replace('reports/complete_soc','reports/optimization/complete_soc/'+name)
        code=source.split("python3 - <<'PY'\n",1)[1].split('\nPY',1)[0];ast.parse(code,feature_version=(3,6))
        os.environ.update(XPIAN_TAG=tag,XPIAN_GATE_DIRECT_PRELOAD='1',XPIAN_GATE_TIMED='0',XPIAN_ACK_REVIEW=str(report/'activity-mapping/native-review-first'/name/'mapped-ack-interface.json'))
        bench=ROOT/'build/optimization/complete_soc'/name/'complete_soc_tb.sv';before=bench.read_bytes();exec(compile(code,'actual-mapped-bench-preparation','exec'),{})
        assert bench.read_bytes()==before
        result=(bench.parent/'gate_tb.sv').read_text();assert 'C_FINAL_ENERGY_MAPPED_ACK' in result and 'inspect_pc' not in result
        records.append(dict(variant=name,tag=tag,Python36=True,actual_mapped_bench_prepared=True,CPU_not_run=True,original_CPU_bench_unchanged=True))
    (report/'recovery/final-ack-observer/mapped-preparation.json').write_text(json.dumps(records,indent=2));print(json.dumps(records),flush=True)

if __name__=='__main__':main()

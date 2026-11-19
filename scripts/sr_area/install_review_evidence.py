"""Install already CRC-verified own actual review inputs, preserving overwritten local copies."""
from pathlib import Path
import argparse,json,shutil
ROOT=Path(__file__).resolve().parents[2];REPORT=ROOT/'reports/optimization/ffn_sr_area'

def main():
    p=argparse.ArgumentParser();p.add_argument('label');a=p.parse_args();source=REPORT/'received'/a.label/'native-evidence';receipt=json.loads((source.parent/'receipt.json').read_text())
    if not receipt['CRC_passed']:raise RuntimeError('Read complete CRC reception first')
    rows=[]
    for f in source.rglob('*'):
        if not f.is_file():continue
        rel=f.relative_to(source);target=ROOT/rel;equal=target.exists() and target.read_bytes()==f.read_bytes()
        own=rel.as_posix().startswith(('reports/optimization/ffn_sr_area/','reports/optimization/complete_soc/ffn_sra_','reports/server/complete_soc_sm40_opt_ffn_sra_','build/server/complete_soc_sm40_opt_ffn_sra_','build/optimization/complete_soc/ffn_sra_','build/optimization/rtl_sources/ffn_sra_','constraints/ffn_sr_area/'))
        if not own and not equal:
            rows.append(dict(path=rel.as_posix(),byte_equal=False,native_source_retained_in_verified_archive=True,unrelated_local_source_not_overwritten=True));continue
        if not equal:
            if target.exists():
                before=REPORT/'recovery/local-review-install'/a.label/rel;before.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(target),str(before))
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(str(f),str(target))
        if target.read_bytes()!=f.read_bytes():raise RuntimeError('Installed actual review input differs '+str(rel))
        rows.append(dict(path=rel.as_posix(),byte_equal=True,already_equal=equal))
    out=REPORT/'deployment'/('review-inputs-'+a.label+'.json');out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(dict(CRC_passed=True,files=rows,native_CPU_or_EDA_rerun=False),indent=2));print('CFE_ACTUAL_REVIEW_INPUTS_INSTALLED',a.label,len(rows),flush=True)

if __name__=='__main__':main()

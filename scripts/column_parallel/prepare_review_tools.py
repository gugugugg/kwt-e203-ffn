"""Reuse inventory/query mechanics, never historical polarity correction lists."""
import ast
import json
from prepare import ROOT,REPORT


def main():
    records=[]
    names=['literature_power_phase_inventory.py','literature_power_phase_connectivity.py',
           'literature_power_phase_prepare.py','literature_power_phase_review.py',
           'assemble_ffn_literature_power_review.py','check_ffn_literature_power_probe.py']
    for name in names:
        path=ROOT/'scripts'/name
        text=path.read_text(encoding='utf-8').replace('ffn_literature_power','ffn_column_parallel')
        text=text.replace('literature_power_phase_','column_parallel_phase_')
        text=text.replace('LITERATURE_POWER','COLUMN_PARALLEL')
        text=text.replace('from ffn_column_parallel import REPORT,dump\n','from ffn_column_parallel import REPORT,dump,review_group\n')
        target=path.with_name(name.replace('literature_power','column_parallel'))
        ast.parse(text,feature_version=(3,6));target.write_text(text,encoding='utf-8')
        records.append(dict(source=path.relative_to(ROOT).as_posix(),target=target.relative_to(ROOT).as_posix(),
                            purpose='Generate pending actual-final evidence/drafts; no inherited correction set is accepted'))
    source=ROOT/'scripts/server/literature_power_segment_query.tcl'
    (ROOT/'scripts/server/column_parallel_segment_query.tcl').write_bytes(source.read_bytes())
    for name in ['query_ffn_literature_power_segments.py','query_ffn_literature_power_additional_segments.py',
                 'query_ffn_literature_power_corrected_phase.py']:
        path=ROOT/'scripts/server'/name
        text=path.read_text(encoding='utf-8').replace('ffn_literature_power','ffn_column_parallel')
        text=text.replace('literature_power_segment_query.tcl','column_parallel_segment_query.tcl')
        text=text.replace('LITERATURE_POWER','COLUMN_PARALLEL')
        text=text.replace("default=['ffn_lit_'+s for s in ['WE','IE','BA','BW']]", "default=['ffn_cp_C16']")
        target=path.with_name(name.replace('ffn_literature_power','ffn_column_parallel'))
        ast.parse(text,feature_version=(3,6));target.write_text(text,encoding='utf-8')
        records.append(dict(source=path.relative_to(ROOT).as_posix(),target=target.relative_to(ROOT).as_posix()))
    (REPORT/'review-tool-derivation.json').write_text(json.dumps(dict(files=records,
        old_correction_lists_copied=False,actual_final_inputs_required=True,
        passed_review_or_native_probe_claimed=False),indent=2))
    print('COLUMN_REVIEW_MECHANICS_PREPARED',len(records))


if __name__=='__main__':main()

"""Run phase inspection/probing separately for each bank-overlap checkpoint."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/q16_staged'))
import phase
import segments


def bind(mode,native=False,variant=None):
    assert variant or mode in ('I','N')
    name=variant or 'ffn_s1_bank_'+mode
    rel=Path('reports/optimization')/name
    report=ROOT/rel
    archive=ROOT if native else report/'received/inputs/native-evidence'
    review=archive/rel/'activity-mapping/native-review-next'/name
    phase.NAME,phase.REL,phase.REPORT,phase.ARCHIVE,phase.REVIEW=name,rel,report,archive,review
    segments.NAME,segments.REPORT=name,report
    segments.FOLDER=report/'activity-mapping/native-review-next'/name/'phase-extra-segments'
    return name,report,archive,review


def targets(review):
    segments.targets()
    target=review/'phase-extra-segments/targets.json'
    rows=json.loads(target.read_text())
    seen={(row['kind'],row['name']) for row in rows}
    cells=json.loads((review/'inventory.json').read_text())['cells']
    def add(path,pin):
        entry=('pin',path+'/'+pin)
        if entry not in seen:
            rows.append(dict(kind=entry[0],name=entry[1]))
            seen.add(entry)
    for path,cell in cells.items():
        if path.startswith(('shared_memory/parameter_committed_reg','shared_memory/shift_committed_reg')):
            for pin in ('D','Q','QN'):
                if pin in cell['pins']:
                    add(path,pin)
        if cell['ref']=='RAMSP4096X16' and path.startswith(tuple(
                'shared_memory/memory/banks_%d__'%bank for bank in (8,9,10,14))):
            for pin in ('CEN','GWEN','CLK'):
                add(path,pin)
            for stem,bits in (('A',12),('D',16),('Q',16),('WEN',16)):
                for bit in range(bits):
                    add(path,'%s[%d]'%(stem,bit))
    target.write_text(json.dumps(rows,indent=2)+'\n')


if __name__=='__main__':
    action,mode=sys.argv[1:3]
    name,report,archive,review=bind(mode)
    if action=='verify':
        from review_local import verify_probe
        verify_probe(name,report,review,sys.argv[3])
    elif action in ('inspect','assemble'):
        phase.local_review(action)
    else:
        {'targets':lambda:targets(review),'segments':segments.main,'probe':phase.native_probe}[action]()

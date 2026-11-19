"""Package only the current candidate's audited activity rules and evidence."""
from pathlib import Path
import shutil
import sys
import tempfile
import zlib

from phase import ROOT,REPORT,ARCHIVE,REVIEW
from ffn_delivery_archive import write_archive


def pack(attempt):
    names=('physical-cell-phase-review.json','physical-gate-phase-review.json',
           'corrections-draft.json','phase-expectations.json','corrected-injection-collisions.json',
           'macro-physical-probe-pins.json','mapped-ack-interface.json','result-ring-physical-state.json',
           'resolved-q8-phase-inputs.json','probe01-physical-source-review.json')
    inputs=[REVIEW/name for name in names]+list((REVIEW/'reviewed-draft').glob('*'))
    inputs+=list((REVIEW/'analysis-recovery').rglob('*'))
    with tempfile.TemporaryDirectory(dir=REPORT) as tmp:
        root=Path(tmp).resolve()
        files=[]
        for source in inputs:
            if not source.is_file():
                continue
            target=root/source.relative_to(ARCHIVE)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            files.append(target)
        for name in ('resolve_phase.py','select_phase_sources.py','pack_phase.py'):
            source=ROOT/'scripts/q8_q16'/name
            if source.is_file():
                target=root/source.relative_to(ROOT)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,target)
                files.append(target)
        dest=REPORT/('q8-q16-phase-'+attempt+'.tar.gz')
        write_archive(dest,files,root)
        data=dest.read_bytes()
        print(len(data),format(zlib.crc32(data),'08x'))


if __name__=='__main__':
    pack(sys.argv[1])

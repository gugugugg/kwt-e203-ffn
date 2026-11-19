"""Assemble an AH-only reviewed mapping from this checkpoint's actual segments."""
import json
import shutil

from review_branch_local import NAME, REPORT, ROOT, SOURCE, area
from assemble_ffn_sr_area_review import assemble


def main():
    rel = area.REPORT.relative_to(SOURCE)/'activity-mapping/native-review-branch'/NAME/'additional-segments'
    origin = REPORT/'received/eco3-segments/native-evidence'/rel
    target = SOURCE/rel
    if json.loads((origin/'targets.json').read_text())!=json.loads((target/'targets.json').read_text()):
        raise RuntimeError('Native target inputs differ from AH local segment inventory')
    for path in origin.iterdir():
        shutil.copyfile(path,target/path.name)
    assemble(NAME)


if __name__=='__main__':
    main()


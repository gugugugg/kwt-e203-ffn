import json
from prepare import ROOT,REPORT

record=json.loads((REPORT/'source-package.json').read_text())
source='expected_archive='+repr(dict(bytes=record['bytes'],crc32=record['crc32']))+'\n'
source+=(ROOT/'scripts/mac_slice_study/install_formal.py').read_text()
(REPORT/'native-actions').mkdir(exist_ok=True)
(REPORT/'native-actions/install-formal.py').write_text(source)

import json
from prepare import ROOT,REPORT

assert json.loads((REPORT/'replay-local-compiled.json').read_text())['passed']
record=json.loads((REPORT/'source-package.json').read_text())
source='expected_archive='+repr(dict(bytes=record['bytes'],crc32=record['crc32']))+'\n'
source+=(ROOT/'scripts/mac_slice_study/start_synthesis.py').read_text()
(REPORT/'native-actions/start-synthesis.py').write_text(source)

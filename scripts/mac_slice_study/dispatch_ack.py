import json
from prepare import ROOT,REPORT

sync=json.loads((REPORT/'local-sync.json').read_text())
small={k:sync[k] for k in ['files','bytes','destination','all_bytes_equal','selected_unchanged']}
source='local_sync='+repr(small)+'\n'+(ROOT/'scripts/mac_slice_study/final_native_receipt.py').read_text()
(REPORT/'native-actions/final-native-ack.py').write_text(source)

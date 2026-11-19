"""Resolve four actual same-segment alias overwrites in the AH probe."""
import json
from pathlib import Path
import shutil


def reconcile(folder):
    def load(name):
        return json.loads((folder/name).read_text())
    inv=load('inventory.json')
    conn=load('connectivity.json')
    draft=load('corrections-draft.json')
    prior=folder/'analysis-recovery/probe01'
    prior.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(folder/'corrections-draft.json',prior/'corrections-draft.json')
    shutil.copyfile(folder/'phase-expectations.json',prior/'phase-expectations.json')
    if not (prior/'reviewed-draft').exists():
        shutil.copytree(folder/'reviewed-draft',prior/'reviewed-draft')
    suppressed=set()
    dedup=set()
    reviewed=[]
    reps=conn['representatives']
    for segment, drivers in conn['drivers'].items():
        if len(drivers)!=1:
            continue
        driver=drivers[0]
        pins=inv['cells'][driver['cell']]['pins']
        if segment.endswith('/cmt_dpc_ena_BAR') and driver['ref']=='CLKNAND2V3_12TR40' and pins['ZN']=='cmt_dpc_ena_BAR':
            reason='Actual CLKNAND output has the same physical segment as positive step_req_dfflr dnxt. Keep that physical representation.'
            assert reps.get(driver['cell'].rsplit('/',1)[0]+'/step_req_dfflr/dnxt[0]')==segment
        elif ('/jtag_' in segment and segment.endswith('/rst_n_BAR') or segment.endswith('/aonrst_catch/io_sync_reset')) and driver['ref']=='CLKMUX2V12_12TR40' and pins['Z']=='io_sync_reset':
            reason='Actual reset catcher mux drives active-high io_sync_reset. Preserve its positive physical representation.'
        elif segment.endswith('/memory/we_BAR') and '/u_e203_dtcm_ram/' in segment and pins[driver['pin']]=='o_dat[55]':
            reason='Actual DTCM physical driver is positive read field o_dat[55]. Write aliases are complementary and downstream uop_cmd_read duplicates the source.'
            dedup.update(net for net,rep in reps.items() if rep==segment and net.endswith('/uop_cmd_read'))
        else:
            continue
        drop=sorted(row['rtl'] for row in draft['aliases'] if row['inverted'] and reps.get(row['gate'],row['gate'])==segment)
        if not drop:
            raise RuntimeError('No opposite aliases for '+segment)
        suppressed.update(drop)
        reviewed.append(dict(segment=segment,driver=driver,pins=pins,reason=reason,suppressed=drop))
    if len(reviewed)!=4 or len(suppressed)!=35 or len(dedup)!=1:
        raise RuntimeError('Unexpected AH alias reconciliation counts: %d %d %d'%(len(reviewed),len(suppressed),len(dedup)))
    draft.update(suppressed_opposite_phase_aliases=sorted(suppressed),deduplicated_positive_aliases=sorted(dedup))
    for name,data in [('corrections-draft.json',draft),('probe01-physical-source-review.json',reviewed)]:
        (folder/name).write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':
    from review_branch_local import SOURCE, area, NAME
    from assemble_ffn_sr_area_review import assemble
    reconcile(area.REPORT/'activity-mapping/native-review-branch'/NAME)
    assemble(NAME)

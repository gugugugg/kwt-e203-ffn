"""Keep the literal producer on each segment found ambiguous by the native probe."""
import shutil
from phase import REVIEW
from resolve_phase import read, write

REASONS = (
    ('CLKMUX2V12_12TR40', 'io_sync_reset', '/io_sync_reset',
     'The reset catcher drives its active-high output; the local active-low reset aliases are consumers.'),
    ('NAND2CV4_12TR40', 'cmt_dpc_ena_BAR', '/step_req_dfflr/dnxt[0]',
     'The NAND is the complement of cmt_dpc_ena. The original step_req_nxt expression equals !dbg_entry_taken_ena because step_req_set already includes that condition.'),
    ('INV10SR_12TR40', 'o_dat[55]', '/u_byp_icb_cmd_buf/o_dat[55]',
     'The actual command-buffer read bit drives the active-low DTCM write signal. Original ram_we is !uop_cmd_read.'),
    ('INV2SR_12TR40', 'mem_cmd_read', '/loading_dma/mem_cmd_read',
     'The actual inverter derives the shared-memory read bit from the opposite PIO direction.'),
)


def select():
    draft, inv, conn = read('corrections-draft.json'), read('inventory.json'), read('connectivity.json')
    reps, expectations = conn['representatives'], read('phase-expectations.json')['nets']
    segments = {}
    for obj in read('probe01-mismatch-nets.json'):
        segments[reps.get(obj,obj)] = expectations[obj]['sources']
    assert len(segments)==5
    backup=REVIEW/'analysis-recovery/probe-attempt-01'
    backup.mkdir(parents=True)
    for name in ('corrections-draft.json','phase-expectations.json'):
        shutil.copyfile(REVIEW/name,backup/name)
    shutil.copytree(REVIEW/'reviewed-draft',backup/'reviewed-draft')
    evidence={}
    opposite, duplicates=set(), set()
    for segment, sources in segments.items():
        driver, = conn['drivers'][segment]
        ref,pin=driver['ref'],driver['pin']
        pins={p:v.strip() for p,v in inv['cells'][driver['cell']]['pins'].items()}
        (_,_,suffix,reason), = [row for row in REASONS if row[:2]==(ref,pins[pin])]
        producer, = [row for row in sources if row['rtl'].endswith(suffix) and not row['inverted']]
        others=[row for row in sources if row['rtl']!=producer['rtl']]
        opposite.update(row['rtl'] for row in others if row['inverted'])
        duplicates.update(row['rtl'] for row in others if not row['inverted'])
        evidence[segment]=dict(driver=driver,pins=pins,producer=producer,other_sources=others,reason=reason)
    draft['suppressed_opposite_phase_aliases']=sorted(opposite)
    draft['deduplicated_positive_aliases']=sorted(duplicates)
    write('corrections-draft.json',draft)
    write('probe01-physical-source-review.json',evidence)
    print('Q16_STAGED_PHYSICAL_SOURCE_REVIEW',len(segments),len(opposite),len(duplicates),flush=True)


if __name__=='__main__':
    select()

"""Compare the returned AH branch netlist to its frozen ECO2 predecessor."""
import re

from prepare import REPORT, dump
from compare_eco import module_parts, normalize, read_netlist


def main():
    oldroot=REPORT/'received/eco-screen/native-evidence'
    newroot=REPORT/'received/eco3-input/native-evidence'
    old='opt_ffn_sr_ah_eco2_final_ss_ema2'
    new='opt_ffn_sr_ah_eco3_final_ss_ema2'
    previous, index=module_parts(read_netlist(oldroot,old))
    candidate, _=module_parts(read_netlist(newroot,new))
    previous[index], count=re.subn(r'(?m)(^\s*)CLKINV0_12TR40(\s+U3968\s*\()',
                                   r'\g<1>CLKINV1_12TR40\g<2>',previous[index])
    if count!=1 or normalize(previous)!=normalize(candidate):
        raise RuntimeError('Unexpected AH branch netlist change')
    dump(REPORT/'eco3-netlist-comparison.json',dict(previous=old,tag=new,passed=True,changed_cells=1,
         instance='U3968',old_ref='CLKINV0_12TR40',new_ref='CLKINV1_12TR40'))
    print('AH_BRANCH_NETLIST_SINGLE_SIZE_VERIFIED')


if __name__=='__main__':
    main()

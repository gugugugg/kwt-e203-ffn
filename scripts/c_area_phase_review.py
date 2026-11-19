"""Record independently examined register, port and clock-gate phases for each actual final."""
from pathlib import Path
from collections import defaultdict,deque
import argparse,json,re
from ffn_c_area import ROOT,REPORT,dump,review_group

def native_index(path):
    groups={};g=None
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            line=line.rstrip('\n')
            if line.startswith('GROUP '):
                _,kind,name=line.split(' ',2);g=dict(kind=kind,name=name,nets=[],drivers=[],driver_inputs=[],notes=[],consumer_count=0);groups[(kind,name)]=g
            elif g is not None:
                key,_,value=line.partition(' ')
                if key=='NET':g['nets'].append(value)
                elif key=='DRIVER':g['drivers'].append(value)
                elif key.startswith('DRIVER_INPUT'):g['driver_inputs'].append(line)
                elif key=='CONSUMER':g['consumer_count']+=1
                else:g['notes'].append(line)
    return groups

def review(name):
    out=REPORT/'activity-mapping'/('native-review-'+review_group(name))/name
    inv=json.loads((out/'inventory.json').read_text());conn=json.loads((out/'connectivity.json').read_text());cells=inv['cells'];reps=conn['representatives']
    act=json.loads((out/'saif-index.json').read_text())['activity']
    def rep(n):return reps.get(n,n)
    native=native_index(out/'segments.rpt')
    additional=out/'additional-segments/segments.rpt'
    if additional.exists():native.update(native_index(additional))
    aliases={};records=[];pending=[];replaced=[];cell_review=[]
    def correction(row,negative,reason,evidence):
        rtl=row['rtl'];entry=dict(rtl=rtl,gate=row['gate'],inverted=bool(negative),reason=reason,evidence=evidence)
        if rtl in aliases and (aliases[rtl]['gate'],aliases[rtl]['inverted'])!=(entry['gate'],entry['inverted']):
            raise RuntimeError('Resolve this independently mapped alias: '+rtl)
        aliases[rtl]=entry
    # The reset value and D cone identify physical encoding, independently of the cell name.
    for row in json.loads((out/'cell-inverted-review-inputs.json').read_text()):
        rtl=row['rtl'];output='Q' if 'Q_net' in row else 'QN';net=row[output+'_net'];negative=None;reason=None
        if '/jp_shift_return[' in rtl and row['ref']=='LALQNV6_12TR40' and output=='QN' and row['pins']['D'].startswith('shift_rdata['):
            negative=True;reason='Own RTL LOW shift-return latch copies positive shift RAM Q; actual D is direct shift_rdata and EN is the actual recorded clock, while literal LALQNV6 udp_tlat output is followed by not QN.'
        elif '/jp_input_return[' in rtl and row['ref']=='LAHQNV4_12TR40' and output=='QN' and row['pins']['D'].strip().startswith('ap_input_rdata['):
            negative=True;reason='Own HIGH input-return latch D is directly connected to the actual positive input macro Q in the native segments. Literal LAHQNV4 enables udp_tlat via !E and inverts its state at QN; physical QN is negative RTL return data.'
        elif '/u_in_stage/r_' in rtl or '/r_event_sync_' in rtl or ('.u_LevelGateway_1_1/inFlight' in rtl) or rtl.endswith('/cmd_stop'):
            negative=True;reason='Original reset-zero PWM/PLIC/I2C state; own DRNQN reset forces physical QN=1, with literal vendor udp_dff+not and own D/feedback cone.'
        elif any(rtl.endswith('/'+s) for s in ['erst_reset_r_r','wdog_reset_r_r','T_356']):
            negative=True;reason='Original PMU set-one state, own direct positive predecessor D and DSNQN output inverter; physical reset QN=0.'
        elif rtl.endswith('/dscl_oen'):
            negative=True;reason='Original delayed scl_oen; own D directly connects predecessor positive scl_oen Q, literal DQN inverts the registered value.'
        elif rtl.endswith('/dout'):
            negative=False;reason='Own EDQN D comes from actual CLKINV of sSDA; vendor QN inverter cancels that encoding, restoring positive dout.'
        elif '/qout_r[' in rtl:
            # Generic original dfflr has reset-zero qout. The observed set pin encoding is explicit.
            if row['ref'].startswith('DRNQN') and output=='QN':
                negative=True;reason='Own original sirv_gnrl_dfflr reset-zero qout; actual DRNQN internal reset-zero DFF has literal inverted QN output, so physical QN is negative original qout.'
            elif row['ref'].startswith('DSNQV') and output=='Q':
                negative=True;reason='Original reset-zero qout; actual DSNQ positive Q is internally set-one and D encodes !dnxt/!qout, so physical Q is negative RTL state.'
            elif output=='QN' and row['ref'].startswith(('DSNQN','DQN')):
                negative=False;reason='Own generic D cone encodes !dnxt when enabled and !qout when held; literal QN restores positive qout. DSNQN internal set-one yields required reset-zero output.'
            elif output=='QN' and row['ref']=='EDQNV6_12TR40' and 'u_sirv_gnrl_rspid_fifo/' in rtl and any(x['ref']=='CLKINV4_12TR40' for x in row.get('D_drivers',[])):
                negative=False;reason='Own response-ID FIFO uses original enabled dffl with no reset. Actual CLKINV4 U40 drives D=!dnxt while literal EDQNV6 udp_edff plus not QN restores positive original qout_r; native D and QN segments establish both inversions.'
        if negative is None:
            pending.append(dict(kind='cell_encoding',rtl=rtl,cell=row['gate'],ref=row['ref']));continue
        evidence=dict(cell=row['gate'],ref=row['ref'],pins=row['pins'],native_output=native.get(('pin',row['gate']+'/'+output)),native_d=native.get(('pin',row['gate']+'/D')),d_drivers=row.get('D_drivers',[]))
        cell_review.append(dict(rtl=rtl,physical_inverted=negative,output=output,net=net,reason=reason,evidence=evidence))
        if negative:
            replaced.append(rtl);correction(dict(rtl=rtl,gate=net),True,reason,evidence)
    # Literal negative ports are compared with original semantics, never inferred from BAR alone.
    for group in json.loads((out/'bar-segment-review-inputs.json').read_text()):
        key=group['segment'];rows=group['aliases'];drivers=group['drivers']
        reason=None
        if '/jtag_' in key and '/rst_n_BAR' in key:
            reason='Actual reset-catch CLKMUX emits active-high sync reset: jtag_TRST is positive, each original CDC rst_n is its complement.'
        elif '/aonrst_catch/io_sync_reset' in key:
            reason='Actual reset-catch CLKMUX emits active-high sync reset; original AON lclkgen rst_n is its complement.'
        elif '/o_axi_aw_fifo/' in key:
            reason='Actual DRNQ stores positive FIFO qout[1]; original i_rdy/i_axi_awready are the complement of that full flag.'
        elif 'ap_input_rows_' in key and any('/we' in x['rtl'] for x in rows):
            reason='Actual input macro WEN/GWEN is active-low; original wrapper we is positive accepted write qualification.'
        elif '/row_stash_' in key and any('/we' in x['rtl'] for x in rows):
            reason='Actual output macro WEN/GWEN uses buffered inverted write qualification; original wrapper we is positive.'
        elif key.endswith('/b_cmd_read') and any('pio_cmd_read' in x['rtl'] for x in rows):
            reason='Actual loading_dma INV drives memory read from positive pio_cmd_read Q; these two mapped RTL aliases describe PIO read and require negative injection here.'
        elif any('fifo_write_banks' in x['rtl'] or 'pair_gate' in x['rtl'] for x in rows):
            # Exact E-pin polarity is reviewed separately below.
            continue
        elif drivers:
            ref=drivers[0]['ref']
            if ref.startswith(('CLKINV','INV')):
                reason='Own actual inverter after the positive RTL expression/register output; original consumers and literal vendor not preserve the negative segment.'
            elif ref.startswith(('NAND','CLKNAND','NOR4')):
                reason='Own original valid/enable/count/activity expression is the positive AND/OR/full predicate; actual literal NAND/NOR computes its complement.'
            elif any(x['rtl'].endswith('/wbck_o_ready') or x['rtl'].endswith('/alu_wbck_i_ready') for x in rows):
                reason='Own actual longp_wbck_o_valid AND drives negative ready branch; original ALU ready is !longp_wbck_o_valid under its existing arbiter priority.'
            elif '/u_e203_dtcm_ram/' in key:
                reason='Own SRAM control wrapper carries complemented write/read through literal buffer/inverter chain; original ram_we is positive write, physical memory WE is active-low.'
            elif '/u_e203_lsu_splt_stage/' in key and ref.startswith('BUF'):
                reason='Own positive generic FIFO Q passes through actual CLKINV4 then BUFV7RD; both original o_vld and qout aliases require negative phase on that segment.'
            elif ref.startswith('DSNQN') and key.endswith('/reset_BAR'):
                reason='Own PMU T_356 positive state is exposed through literal DSNQN negative QN to this reset alias.'
        if reason is None:
            pending.append(dict(kind='net_semantics',segment=key,aliases=rows,drivers=drivers));continue
        evidence=dict(drivers=drivers,driver_cells=[cells[x['cell']] for x in drivers],native=[native.get(('net',x['gate'])) for x in rows])
        for row in rows:
            negative=True
            if '/jtag_' in key and row['rtl'].endswith('/jtag_TRST'):negative=False
            if '/o_axi_aw_fifo/' in key and '/qout[' in row['rtl']:negative=False
            correction(row,negative,reason,evidence)
        records.append(dict(segment=key,reason=reason,aliases=len(rows)))
    # A wrapper's original enable/test_enable is positive at the actual ICG E/TE pin.
    unary=defaultdict(list)
    vendor=(out/'vendor-functions.v').read_text()
    models={m.group(1):m.group(2).split('specify')[0] for m in re.finditer(r'\bmodule\s+(\w+)\s*\(([\s\S]*?)endmodule',vendor)}
    for path,cell in cells.items():
        if cell['ref'] not in models:continue
        body=models[cell['ref']]
        if 'I' in cell['pins'] and ('Z' in cell['pins'] or 'ZN' in cell['pins']):
            pin='Z' if 'Z' in cell['pins'] else 'ZN'
            expected_gate='buf' if pin=='Z' else 'not'
            if not re.search(r'\b'+expected_gate+r'\s+\w+\s*\(\s*'+pin+r'\s*,\s*I\s*\)',body):continue
            a=conn['pins'].get(path+'/I');b=conn['pins'].get(path+'/'+pin)
            if not a or not b:continue
            a,b=rep(a),rep(b);edge=dict(cell=path,ref=cell['ref'],pins=cell['pins'],inverted=pin=='ZN')
            unary[a].append((b,pin=='ZN',edge));unary[b].append((a,pin=='ZN',edge))
    def link(a,b):
        a,b=rep(a),rep(b);queue=deque([(a,False,[])]);seen=set()
        while queue:
            n,phase,path=queue.popleft()
            if n==b:return phase,path
            if n in seen:continue
            seen.add(n)
            for nxt,flip,edge in unary[n]:queue.append((nxt,phase^flip,path+[edge]))
        return None
    gate_reviews=[]
    for row in inv['mappings']:
        if row['cell'] or not row['rtl'].endswith(('/enable','/test_enable')):continue
        rtlbase=row['rtl'].rsplit('/',1)[0]
        actualbase=re.sub(r'\[(\d+)\]\.',r'_\1__',rtlbase).replace('.','_')
        cellpath=actualbase+'/cell_gate'
        if cellpath not in cells:continue
        pin='E' if row['rtl'].endswith('/enable') else 'TE'
        n=conn['pins'].get(cellpath+'/'+pin)
        if n is None:pending.append(dict(kind='gate_pin',rtl=row['rtl']));continue
        trace=link(row['gate'],n)
        if trace is None:pending.append(dict(kind='gate_connection',rtl=row['rtl'],gate=row['gate'],pin_net=n));continue
        negative,chain=trace
        evidence=dict(actual_pin=cellpath+'/'+pin,actual_net=n,unary_chain=chain,native_pin=native.get(('pin',cellpath+'/'+pin)))
        gate_reviews.append(dict(rtl=row['rtl'],physical_inverted=negative,evidence=evidence))
        if negative:correction(row,True,'Own mapped enable is connected to actual positive ICG '+pin+' through the listed literal inverter/buffer chain.',evidence)
    dump(out/'physical-cell-phase-review.json',cell_review)
    dump(out/'physical-gate-phase-review.json',gate_reviews)
    dump(out/'phase-review-pending.json',pending)
    dump(out/'corrections-draft.json',dict(variant=name,actual_tag=inv['tag'],passed=False,aliases=list(aliases.values()),replace_native_cell_aliases=replaced,suppressed_opposite_phase_aliases=[],reviewed_bar_segments=records,pending=len(pending),native_probe_passed=False))
    print(name,'draft_aliases',len(aliases),'inverted',sum(x['inverted'] for x in aliases.values()),'replaced_cells',len(replaced),'gates_reviewed',len(gate_reviews),'pending',len(pending),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('variants',nargs='+')
    for name in p.parse_args().variants:review(name)

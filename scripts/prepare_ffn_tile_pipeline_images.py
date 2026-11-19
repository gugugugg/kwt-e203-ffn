"""Reproduce Tile-order weight files and prove inversion against the frozen Q2 words."""
import struct
from ffn_tile_pipeline import ROOT,BUILD,REPORT,load,copy_tree,dump


def prepare(name):
    manifest=load(name);lanes=16 if manifest['features']['lanes16'] else 8
    destination=BUILD/'images'/(manifest['layout']+'_%d'%lanes)
    record=destination/'loading-layout.json'
    if record.exists():return destination
    source=ROOT/'build/optimization/images/Q2_range'
    copy_tree(source,destination)
    layers=[]
    for layer in range(12):
        path=destination/('linear_layer_%02d_parameters.hex'%layer)
        original32=[int(x,16) for x in path.read_text().split()]
        raw=b''.join(struct.pack('<I',v) for v in original32)
        halves=list(struct.unpack('<%dH'%(len(raw)//2),raw));ordered=list(halves)
        if manifest['layout']=='tile':
            for tile in range(256//lanes):
                for inner in range(64):
                    for lane in range(lanes):ordered[(tile*64+inner)*lanes+lane]=halves[inner*256+tile*lanes+lane]
            restored=list(ordered)
            for tile in range(256//lanes):
                for inner in range(64):
                    for lane in range(lanes):restored[inner*256+tile*lanes+lane]=ordered[(tile*64+inner)*lanes+lane]
            if restored!=halves:raise RuntimeError('Tile permutation did not invert: layer '+str(layer))
        payload=struct.pack('<%dH'%len(ordered),*ordered)
        values=struct.unpack('<%dI'%(len(payload)//4),payload)
        path.write_text(''.join('%08x\n'%v for v in values))
        layers.append(dict(layer=layer,words32=len(values),weights_int16=16384,bias_int64=256,inverse_matches=True))
    result=dict(passed=True,layout=manifest['layout'],lanes=lanes,layers=layers,
        order='tile,inner,lane' if manifest['layout']=='tile' else 'inner,column',
        byte_order='little',external_bias_bits=64,quantization='unchanged Q2',
        input_address='0xA0000000',output_address='0xA0010000',parameter_address='0xA0020000',shift_address='0xA003A000',
        alignment_bytes=4,weight_words32=8192,bias_words32=512,shift_words32=64)
    dump(record,result)
    return destination


if __name__=='__main__':
    import sys
    for name in sys.argv[1:]:print(prepare(name))

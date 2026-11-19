"""Pack the frozen linear-task fixtures into the two-page wire order."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
IMAGES=ROOT/"build/optimization/ffn_ar_area/frozen/images"


def read_words(path):
    return [int(word,16) for word in path.read_text().splitlines()]


def pack(case):
    number=2*case+1
    source=read_words(IMAGES/"case_sources.hex")[number]
    inputs=read_words(IMAGES/("task_%02d_shared.hex"%number))[:3168]
    parameters=read_words(IMAGES/("linear_layer_%02d_parameters.hex"%source))
    shifts=read_words(IMAGES/("linear_layer_%02d_metadata.hex"%source))
    assert len(inputs)==3168 and len(parameters)==8704 and len(shifts)==64
    halves=[(word>>bit)&65535 for word in inputs for bit in (0,16)]
    identity=[row*64+k for first in range(0,96,12) for k in range(64) for row in range(first,first+12)]
    identity.extend(row*64+k for k in range(64) for row in range(96,99))
    packed=[halves[identity[i]]|(halves[identity[i+1]]<<16) for i in range(0,6336,2)]
    packets=[]
    for tile in range(16):
        col=tile*16
        bias=parameters[8192+2*col:8192+2*(col+16)]
        assert all(bias[i+1]==(0xffffffff if bias[i]>>31 else 0) for i in range(0,32,2))
        packets.append(bias[::2]+shifts[col//4:col//4+4]+[
            word for k in range(64) for word in parameters[tile*512+k*8:tile*512+k*8+8]])
    source_words=packed+[0]*(32768-len(packed))+[word for packet in packets for word in packet]
    order=list(range(3168))+list(range(32768,41280))
    assert len(order)==len(set(order))==11680
    return order,[source_words[word] for word in order]



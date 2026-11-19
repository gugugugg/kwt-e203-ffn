"""Extend the existing actual-layer harness with a timed ICB memory and DMA API."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def prepare():
    text=(ROOT/'tb/ffn_residual/sim_unified.cpp').read_text()
    memory='''
#if LOADING_DMA_ENABLED
    std::vector<uint32_t> memory=std::vector<uint32_t>(131072,0);
    bool mem_pending=false,mem_valid=false,mem_error=false;
    unsigned mem_delay=0;uint32_t mem_data=0;
    void memory_settle(){
        top.ld_cmd_ready=!mem_pending&&!mem_valid&&(!mixed_output||cycles%17>1);
        top.ld_rsp_valid=mem_valid;top.ld_rsp_rdata=mem_data;top.ld_rsp_err=mem_error;
    }
    void memory_edge(bool command,bool response,uint32_t address,bool read,uint32_t data,unsigned mask){
        if(response)mem_valid=false;
        if(mem_pending&&--mem_delay==0){mem_pending=false;mem_valid=true;}
        if(command){
            mem_error=address<0xa0000000u||address>=0xa0080000u||(address&3);
            if(!mem_error){
                size_t index=(address-0xa0000000u)/4;
                if(read)mem_data=memory[index];
                else for(unsigned b=0;b<4;++b)if(mask&(1u<<b))memory[index]=(memory[index]&~(255u<<(b*8)))|(data&(255u<<(b*8)));
            }
            mem_pending=true;mem_delay=2;
        }
    }
    void memory_upload(unsigned address,const std::vector<uint16_t>& values){
        for(size_t i=0;i<values.size();i+=2)memory[(address-0xa0000000u)/4+i/2]=uint32_t(values[i])|(uint32_t(values[i+1])<<16);
    }
    void dma(unsigned address,unsigned words,unsigned direction){
        wr(0x40,address);wr(0x44,words);wr(0x48,direction);
        if(rd(0x50)&4)throw std::runtime_error("DMA transaction error");
    }
#endif
'''
    text=text.replace('    void settle(){top.clk=0;top.eval();}',memory+'''    void settle(){
#if LOADING_DMA_ENABLED
        memory_settle();
#endif
        top.clk=0;top.eval();
    }''')
    text=text.replace('        top.clk=1;top.eval();context.timeInc(1);++cycles;', '''
#if LOADING_DMA_ENABLED
        bool mc=top.ld_cmd_valid&&top.ld_cmd_ready,mr=top.ld_rsp_valid&&top.ld_rsp_ready;
        uint32_t ma=top.ld_cmd_addr,md=top.ld_cmd_wdata;bool read=top.ld_cmd_read;unsigned mask=top.ld_cmd_wmask;
#endif
        top.clk=1;top.eval();context.timeInc(1);++cycles;
#if LOADING_DMA_ENABLED
        memory_edge(mc,mr,ma,read,md,mask);
#endif''')
    text=text.replace('addr==32||addr==52','addr==32||addr==52||addr==0x50')
    text=text.replace('        for(size_t i=0;i<values.size();) {', '''
#if LOADING_DMA_ENABLED
        unsigned address=kind==1?0xa0020000u:0xa003a000u;
        memory_upload(address,values);dma(address,unsigned(values.size()/2),1);return;
#endif
        for(size_t i=0;i<values.size();) {''',1)
    text=text.replace('        for(size_t i=first;i<end;){', '''
#if LOADING_DMA_OUTPUT
        if(packed_output&&!mixed_output){
            dma(0xa0010000u+unsigned(first*2),unsigned((end-first)/2),2);
            for(size_t i=first;i<end;++i){
                uint32_t word=memory[(0x10000+i*2)/4];int16_t value=int16_t(word>>((i&1)*16));
                if(value!=expected[i])throw std::runtime_error("DMA result writeback mismatch");
            }
            return;
        }
#endif
        for(size_t i=first;i<end;){''')
    old='std::snprintf(name,sizeof(name),"%s/linear/layer_%02d_parameters.bin",package.c_str(),layer);load(1,binary<uint16_t>(name));'
    new='''std::snprintf(name,sizeof(name),"%s/linear/layer_%02d_parameters.bin",package.c_str(),layer);
        auto parameters=binary<uint16_t>(name);
#if LOADING_DMA_TILE
        auto original=parameters;
        for(unsigned tile=0;tile<256/LOADING_DMA_LANES;++tile)for(unsigned inner=0;inner<64;++inner)for(unsigned lane=0;lane<LOADING_DMA_LANES;++lane)
            parameters[(tile*64+inner)*LOADING_DMA_LANES+lane]=original[inner*256+tile*LOADING_DMA_LANES+lane];
#endif
        load(1,parameters);'''
    if old not in text:raise RuntimeError('Existing actual-layer parameter load changed')
    text=text.replace(old,new)
    text=text.replace('        if(!RESIDUAL_STREAM)load(0,inputs);', '''
#if LOADING_DMA_ENABLED
        memory_upload(0xa0000000u,inputs);
#endif
        if(!RESIDUAL_STREAM)load(0,inputs);''')
    text=text.replace('                for(size_t j=row*64;j<end;){', '''
#if LOADING_DMA_ENABLED
                dma(0xa0000000u+unsigned(row*128),unsigned((end-row*64)/2),1);return;
#endif
                for(size_t j=row*64;j<end;){''')
    out=ROOT/'tb/ffn_loading_dma/sim_unified.cpp';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(text)
    return out


if __name__=='__main__':print(prepare())

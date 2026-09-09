#!/usr/bin/env python3
"""Pinned-source FXC experiments. Counts DXBC operations, never hardware time."""
from pathlib import Path
import argparse, collections, hashlib, itertools, json, re, subprocess
HERE=Path(__file__).resolve().parent
COMMON=r'''
Texture2D<float4> atlas : register(t0);
SamplerState samp : register(s0);
cbuffer Constants : register(b0) {
    float4 atlasTexelSize; float4 clipRect;
    float4x4 objectToClip; float alwaysGammaSpace;
};
struct Input { float4 vertex:POSITION; float4 color:COLOR0; float4 uv:TEXCOORD0; };
struct Varyings {
    float4 vertex:SV_POSITION; float4 color:COLOR0;
    float4 prepared:TEXCOORD0; float4 mask:TEXCOORD1; float4 outline:TEXCOORD2;
};
'''
VERT=r'''
Varyings main(Input v) {
    Varyings o;
    o.vertex=mul(objectToClip,v.vertex);
    float4 outline; float mode,format;
    R3Unpack(v.uv.zw,outline,mode,format);
    o.prepared=R3Prepare(v.uv.xy,mode,format);
    o.color=TexpixUIVertexColor(v.color,alwaysGammaSpace);
    o.outline=R3Outline(format,o.color,outline);
    o.mask=v.vertex;
    return o;
}
'''
FRAG=r'''
float4 main(Varyings i):SV_Target {
    float raw=atlas.Sample(samp,R3UV(i.prepared,atlasTexelSize)).r;
    float4 color=R3Shade(raw,i.prepared,i.color,i.outline);
#if RECT_CLIP
    float2 m=saturate((clipRect.zw-clipRect.xy-abs(i.mask.xy))*i.mask.zw);
    color.a*=m.x*m.y;
#endif
#if ALPHA_CLIP
    clip(color.a-0.001);
#endif
    return color;
}
'''
def run(cmd):
    p=subprocess.run(list(map(str,cmd)),capture_output=True,text=True)
    if p.returncode:raise RuntimeError(' '.join(map(str,cmd))+'\n'+p.stdout+p.stderr)
    return p.stdout

def source(config):
    defs=''.join(f'#define {k} {v}\n' for k,v in config.items())
    return defs+(HERE/'baseline.hlsl').read_text(encoding='utf-8')+'\n'+(HERE/'Candidates.hlsl').read_text(encoding='utf-8')

def count_ops(text):
    counter=collections.Counter();temps=None;ops=[]
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith('//'):continue
        token=line.split()[0]
        # sample_indexable(texture2d)(float,float,float,float) is ONE operation.
        op=token.split('(')[0]
        if op=='dcl_temps':temps=int(line.split()[1])
        if op.startswith('dcl_') or re.match(r'^[pvcghd]s_\d',op):continue
        if re.fullmatch(r'[a-z][a-z0-9_]*',op):counter[op]+=1;ops.append(line)
    return dict(instructions=sum(counter.values()),temps=temps,opcodes=dict(counter)),ops

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fxc',type=Path,required=True);ap.add_argument('--output',type=Path,default=Path('round3-results'))
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    raw=(HERE/'baseline.hlsl').read_text(encoding='utf-8').encode()
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if blob!='93be552174ab8974cb6158e714b7e2e5e087ee51':raise ValueError('Wrong frozen baseline')
    results=[]
    for table,bias,payload,address in itertools.product(range(2),range(2),range(3),range(2)):
        name=f't{table}-b{bias}-p{payload}-a{address}'
        cfg=dict(R3_TABLE=table,R3_BIAS=bias,R3_PAYLOAD=payload,R3_ADDRESS=address,R3_UNPACK=0)
        for profile,rect,alpha in itertools.product(['ps_4_0','ps_5_0'],range(2),range(2)):
            stem=f'{profile}-{name}-r{rect}-c{alpha}'
            path=a.output/(stem+'.hlsl');asm=a.output/(stem+'.asm');obj=a.output/(stem+'.dxbc')
            path.write_text(source(dict(cfg,RECT_CLIP=rect,ALPHA_CLIP=alpha))+'\n'+COMMON+FRAG,encoding='utf-8')
            run([a.fxc,'/nologo','/T',profile,'/E','main','/O3','/Fc',asm,'/Fo',obj,path])
            counts,ops=count_ops(asm.read_text(encoding='utf-8-sig'))
            result=dict(variant=name,profile=profile,rect=rect,alpha=alpha,**counts);results.append(result)
            if profile=='ps_4_0' and rect==alpha==0:print(json.dumps(result),flush=True)
            if profile=='ps_4_0' and rect==alpha==0 and counts['instructions']<20:
                print('ASM '+name+'\n'+'\n'.join(ops),flush=True)
    for payload,unpack in itertools.product(range(3),range(2)):
        cfg=dict(R3_TABLE=0,R3_BIAS=0,R3_PAYLOAD=payload,R3_ADDRESS=0,R3_UNPACK=unpack)
        stem=f'vs_4_0-p{payload}-unpack{unpack}'
        path=a.output/(stem+'.hlsl');asm=a.output/(stem+'.asm');obj=a.output/(stem+'.dxbc')
        path.write_text(source(cfg)+'\n'+COMMON+VERT,encoding='utf-8')
        run([a.fxc,'/nologo','/T','vs_4_0','/E','main','/O3','/Fc',asm,'/Fo',obj,path])
        counts,ops=count_ops(asm.read_text(encoding='utf-8-sig'))
        result=dict(variant=stem,profile='vs_4_0',**counts);results.append(result)
        print(json.dumps(result),flush=True)
    report=dict(scope='FXC minimal stage wrappers; NOT Unity, hardware ISA, or GPU timings',
        baseline_commit='e55897ddca6259cc8249f0306bcb2c1900f0571c',baseline_blob=blob,fxc=str(a.fxc),
        candidate_sha256=hashlib.sha256((HERE/'Candidates.hlsl').read_bytes()).hexdigest(),results=results)
    (a.output/'fxc.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('BASELINE ps_4_0 20; all sample_indexable operations included. Raw reports attached.')
if __name__=='__main__':main()

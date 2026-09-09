#!/usr/bin/env python3
"""Generate paired D3D11 stages from the exact baseline and actual fast UI include."""
from pathlib import Path
import argparse, hashlib, json
from experiment import run, count_ops
HERE=Path(__file__).resolve().parent
FAST=HERE.parents[1]/'Packages/com.ruccho.texpix/Runtime/Shaders/TexpixUIFast.hlsl'
COMMON=r'''
Texture2D<float4> atlas:register(t0); SamplerState samp:register(s0);
cbuffer Constants:register(b0) {float4 ts;float4 rect;float4x4 matrix;float4 flags;};
struct Input {float4 vertex:POSITION;float4 color:COLOR0;float4 uv:TEXCOORD0;};
struct Varyings {float4 vertex:SV_POSITION;float4 color:COLOR0;float4 p:TEXCOORD0;float4 mask:TEXCOORD1;float4 alt:TEXCOORD2;};
'''
VERT=r'''
Varyings main(Input v) {
    Varyings o; o.vertex=mul(matrix,v.vertex);
#if FAST_UI
    TexpixPrepareUI(v.uv,v.color,flags.x,o.p,o.color,o.alt);
#else
    float mode,format;
    TexpixUnpackOutline(v.uv.zw,o.alt,mode,format);
    o.p=TexpixPrepareCoverage(v.uv.xy,mode,format);
    o.color=TexpixUIVertexColor(v.color,flags.x);
#endif
    o.mask=float4(v.vertex.xy,11.0,9.0); return o;
}
'''
FRAG=r'''
float4 main(Varyings i):SV_Target {
    float raw=atlas.Sample(samp,TexpixPreparedAtlasUV(i.p,ts)).r;
#if FAST_UI
    float4 color=TexpixShadeUI(raw,i.p,i.color,i.alt);
#else
    float4 color=TexpixShadePrepared(raw,i.p,i.color,i.alt);
#endif
#if RECT_CLIP
    float2 m=saturate((rect.zw-rect.xy-abs(i.mask.xy))*i.mask.zw);
    color.a*=m.x*m.y;
#endif
#if ALPHA_CLIP
    clip(color.a-0.001);
#endif
    return color;
}
'''
COMPUTE=r'''
struct Case {float4 data;float4 fill;float4 outline;float4 extra;};
StructuredBuffer<Case> cases:register(t1); RWStructuredBuffer<uint4> outputData:register(u0);
[numthreads(64,1,1)]
void main(uint3 id:SV_DispatchThreadID) {
    uint k=id.x; if(k>=(uint)flags.y)return;
    Case c=cases[k];
    float mode=c.data.z,format=c.data.w;
    float4 oldp=TexpixPrepareCoverage(c.data.xy,mode,format);
    float4 p=oldp;
    p.w=format>=0.5?c.data.x*0.5:0.75;
    int jitter=(int)c.extra.w;
    oldp.z=asfloat(asuint(oldp.z)+jitter);
    oldp.w=asfloat(asuint(oldp.w)-jitter);
    p.z=asfloat(asuint(p.z)+jitter);
    float4 alt=format>=0.5?c.fill:c.outline;
    float raw=atlas.SampleLevel(samp,TexpixPreparedAtlasUV(oldp,ts),0).r;
    float perturbed=saturate((raw*255.0+c.extra.z)/255.0);
    float4 ref=TexpixShadePrepared(perturbed,oldp,c.fill,c.outline);
    float4 now=TexpixShadeUI(perturbed,p,c.fill,alt);
    uint mismatch=any(ref!=now);
    float4 a,b;float am,bm,af,bf;
    TexpixUnpackOutline(c.extra.xy,a,am,af);
    TexpixUnpackUIOutline(c.extra.xy,b,bm,bf);
    uint unpack=any(a!=b)||am!=bm||af!=bf;
    // Independent integer oracle for the actual R8 sample (no perturbation).
    uint byte=(uint)(raw*255.0+0.5);
    uint sub=(uint)floor(c.data.x) % (format>=0.5?8u:4u);
    uint level=format>=0.5?((byte>>sub)&1u)*3u:((byte>>(2u*sub))&3u);
    float4 oracle=level==3u?c.fill:((mode>=1.5&&level>=1u)||(mode>=0.5&&level==2u)?c.outline:float4(0,0,0,0));
    uint wrong=any(oracle!=TexpixShadeUI(raw,p,c.fill,alt));
    outputData[k]=uint4(mismatch,unpack,wrong,0);
}
'''
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--fxc',type=Path,required=True);ap.add_argument('--output',type=Path,default=Path('round3-results'))
    a=ap.parse_args();a.output.mkdir(exist_ok=True,parents=True)
    base=(HERE/'baseline.hlsl').read_text(encoding='utf-8')
    fast=FAST.read_text(encoding='utf-8').replace('#include "Texpix.hlsl"','')
    results=[]
    for gamma in range(2):
        prefix=('#define UNITY_COLORSPACE_GAMMA\n' if gamma else '')+base+'\n'+fast+'\n'+COMMON
        for optimized in range(2):
            for stage in ['vs','ps']:
                for rect in range(2):
                    for alpha in range(2):
                        stem=f'{stage}-f{optimized}-g{gamma}-r{rect}-a{alpha}'
                        text=f'#define FAST_UI {optimized}\n#define RECT_CLIP {rect}\n#define ALPHA_CLIP {alpha}\n'+prefix+(VERT if stage=='vs' else FRAG)
                        path=a.output/(stem+'.hlsl');asm=a.output/(stem+'.asm');obj=a.output/(stem+'.dxbc')
                        path.write_text(text,encoding='utf-8')
                        run([a.fxc,'/nologo','/T',stage+'_4_0','/E','main','/O3','/Fc',asm,'/Fo',obj,path])
                        counts,_=count_ops(asm.read_text(encoding='utf-8-sig'))
                        results.append(dict(stage=stage,fast=optimized,gamma=gamma,rect=rect,alpha=alpha,**counts))
        path=a.output/f'cs-g{gamma}.hlsl';obj=a.output/f'cs-g{gamma}.dxbc'
        path.write_text(prefix+COMPUTE,encoding='utf-8')
        run([a.fxc,'/nologo','/T','cs_5_0','/E','main','/O3','/Fo',obj,path])
    report=dict(scope='Actual fast include vs pinned round-2 include, FXC minimal stage wrappers; NOT Unity',
        fast_sha256=hashlib.sha256(FAST.read_text(encoding='utf-8').encode()).hexdigest(),fxc=str(a.fxc),results=results)
    (a.output/'selected-fxc.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for row in results:print(json.dumps(row),flush=True)
    print('FAST_SOURCE_SHA256 '+report['fast_sha256'])
if __name__=='__main__':main()

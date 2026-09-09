#!/usr/bin/env python3
"""Compile round-2 candidates with FXC. Minimal wrappers, NOT Unity or GPU timings."""
import argparse
from pathlib import Path
import collections
import hashlib
import json
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMES = ['baseline','direct_select','affine_coefficients','product_phases',
         'product_affine','parallel_affine','parallel_scalar']
WRAPPER = r'''
Texture2D<float4> atlas : register(t0);
SamplerState samp : register(s0);
cbuffer Constants : register(b0) { float4 atlasTexelSize; float4 clipRect; };
struct Varyings {
    float4 vertex : SV_POSITION;
    float4 color : COLOR0;
    float4 prepared : TEXCOORD0;
    float4 mask : TEXCOORD1;
    float4 outline : TEXCOORD2;
};
float4 main(Varyings i) : SV_Target {
    float raw=atlas.Sample(samp,TexpixPreparedAtlasUV(i.prepared,atlasTexelSize)).r;
    float4 color=TexpixShadeCandidate(raw,i.prepared,i.color,i.outline);
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
    result=subprocess.run([str(x) for x in cmd],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(' '.join(map(str,cmd))+'\n'+result.stdout+result.stderr)
    return result.stdout

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fxc',type=Path,required=True)
    ap.add_argument('--output',type=Path,default=Path('round2-results'))
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    base=(ROOT/'Packages/com.ruccho.texpix/Runtime/Shaders/Texpix.hlsl').read_text(encoding='utf-8')
    candidate=(HERE/'Candidates.hlsl').read_text(encoding='utf-8')
    results=[]
    for profile in ['ps_4_0','ps_5_0']:
        for index,name in enumerate(NAMES):
            for rect in range(2):
                for alpha in range(2):
                    stem=f'{profile}-{name}-r{rect}-a{alpha}'
                    path=args.output/(stem+'.hlsl');asm=args.output/(stem+'.asm');obj=args.output/(stem+'.dxbc')
                    source=f'#define EXPERIMENT {index}\n#define RECT_CLIP {rect}\n#define ALPHA_CLIP {alpha}\n'+base+'\n'+candidate+'\n'+WRAPPER
                    path.write_text(source,encoding='utf-8')
                    run([args.fxc,'/nologo','/T',profile,'/E','main','/O3','/Fc',asm,'/Fo',obj,path])
                    text=asm.read_text(encoding='utf-8-sig');ops=[];temps=None
                    for line in text.splitlines():
                        line=line.strip()
                        if not line or line.startswith('//'):continue
                        op=line.split()[0]
                        if op=='dcl_temps':temps=int(line.split()[1])
                        if op.startswith('dcl_') or op.startswith(('ps_','vs_')):continue
                        if re.fullmatch(r'[a-z][a-z0-9_]*',op):ops.append(op)
                    results.append(dict(profile=profile,variant=name,rect=bool(rect),alpha=bool(alpha),instructions=len(ops),temps=temps,opcodes=dict(collections.Counter(ops))))
    report=dict(scope='FXC minimal HLSL fragment wrappers; NOT Unity compilation, native ISA, or GPU time',
                fxc=str(args.fxc),baseline_commit='b990a3f24634abdb944b6d2fc073608707d986cb',
                baseline_sha256=hashlib.sha256(base.encode()).hexdigest(),candidate_sha256=hashlib.sha256(candidate.encode()).hexdigest(),results=results)
    (args.output/'fxc.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()

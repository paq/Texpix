#!/usr/bin/env python3
"""Generate a standalone WebGL2 differential test and hardware GPU timing lab.

Helper functions are mechanically translated from the actual HLSL files. This
checks GLSL rasterization, not Unity's compiler, Canvas, stencil or XR behavior.
Requires Python 3.9+ only. Open the output HTML in a GPU-enabled browser.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import re
from pathlib import Path
from validate import HEADER, BASE_FUNCTIONS, NEW_FUNCTIONS, source_functions, BASELINE_SHA

HERE = Path(__file__).resolve().parent
TRANSFORMS = [([0,0], [1,0,0,1], [0,0], [0,0]),
              ([.3125,.1875], [.85,-.18,.18,.85], [.015,-.027], [0,0]),
              ([.03125,.4375], [.91,.13,-.09,.87], [-.011,.009], [.15,-.08])]
UNIFORMS = ['uFormat','uMode','uOffset','uRange','uTransform','uTranslate',
            'uPerspective','uAtlas','uTexelSize']


def translated(source: str, native: bool) -> str:
    source = re.sub(r'#if defined\(TEXPIX_USE_NATIVE_BITS\)\s*(.*?)#else\s*(.*?)#endif',
                    lambda m: m.group(1 if native else 2), source, flags=re.S)
    source = re.sub(r'\(uint\)\(([^()]*)\)', r'uint(\1)', source)
    source = re.sub(r'\((uint|float)\)(\w+)', r'\1(\2)', source)
    for old,new in [('float2','vec2'),('float3','vec3'),('float4','vec4'),('frac','fract')]:
        source = re.sub(r'\b'+old+r'\b', new, source)
    return '#define TEXPIX_LEVEL_FILL 3.0\n'+source


def programs() -> list[dict]:
    baseline = (HERE/'baseline/Texpix.hlsl').read_bytes()
    sha = hashlib.sha1(b'blob '+str(len(baseline)).encode()+b'\0'+baseline).hexdigest()
    if sha != BASELINE_SHA:
        raise ValueError('Frozen baseline checksum mismatch')
    before = source_functions(baseline.decode(), BASE_FUNCTIONS)
    after = source_functions(HEADER.read_text(), NEW_FUNCTIONS)
    result = []
    for kind,clip,alpha in itertools.product(['legacy','portable','native'],range(2),range(2)):
        common = '#version 300 es\nprecision highp float; precision highp int;\n'
        common += translated(before if kind=='legacy' else after,kind=='native')
        prep = 'vec4(f,uMode,uFormat)' if kind=='legacy' else 'TexpixPrepareCoverage(f,uMode,uFormat)'
        vertex = common+'''
layout(location=0) in vec2 aPos;
uniform float uFormat,uMode;
uniform vec2 uOffset,uRange,uTranslate,uPerspective;
uniform vec4 uTransform;
out vec4 vData,vFill,vOutline; out vec2 vMask;
void main() {
    vec2 q=aPos*2.0-1.0;
    vec2 p=vec2(dot(uTransform.xy,q),dot(uTransform.zw,q))+uTranslate;
    gl_Position=vec4(p,0.0,1.0+dot(uPerspective,q));
    vec2 f=aPos*uRange+uOffset;
    vData=PREP;
    vFill=vec4(0.25+0.5*aPos.x,0.5,1.0-0.5*aPos.y,0.625);
    vOutline=vec4(0.75,0.125+0.5*aPos.y,0.5,0.375); vMask=q;
}
'''.replace('PREP',prep)
        shade = '''float level=TexpixExtractLevel(
texture(uAtlas,TexpixAtlasUV(vData.xy,uTexelSize,vData.w)).r,
TexpixSubPixel(vData.xy,vData.w),vData.w);
vec4 color=TexpixShade(level,vFill,vOutline,vData.z);''' if kind=='legacy' else '''
vec4 color=TexpixShadePrepared(
texture(uAtlas,TexpixPreparedAtlasUV(vData,uTexelSize)).r,vData,vFill,vOutline);'''
        fragment = common+'''
uniform sampler2D uAtlas; uniform vec4 uTexelSize;
in vec4 vData,vFill,vOutline; in vec2 vMask; out vec4 outColor;
void main() {
'''+shade
        if clip:
            fragment+='\nvec2 m=clamp((vec2(0.72,0.82)-abs(vMask))*vec2(11.0,9.0),0.0,1.0); color.a*=m.x*m.y;'
        if alpha: fragment+='\nif(color.a<0.001) discard;'
        fragment+='\noutColor=color;\n}\n'
        result.append(dict(kind=kind,clip=clip,alpha=alpha,vertex=vertex,fragment=fragment))
    return result


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--html',type=Path,default=HERE/'texpix_shader_lab.html')
    ap.add_argument('--export-programs',type=Path)
    args=ap.parse_args(); sources=programs()
    data=dict(programs=sources,transforms=TRANSFORMS,uniforms=UNIFORMS,
              candidate_sha256=hashlib.sha256(HEADER.read_bytes()).hexdigest())
    args.html.write_text((HERE/'webgl_template.html').read_text().replace('/*SHADER_DATA*/','const DATA='+json.dumps(data)+';'))
    print(args.html)
    if args.export_programs: args.export_programs.write_text(json.dumps(data,indent=2)+'\n')

if __name__=='__main__': main()

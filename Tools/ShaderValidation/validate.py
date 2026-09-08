#!/usr/bin/env python3
"""Compile the ACTUAL scalar HLSL bodies as C++ and check against a frozen oracle.

Requires Python 3.9+ and clang++ or g++. No third-party Python packages.
Run from any directory. --baseline is a directory containing the baseline Texpix.hlsl.
This is float32/source-level validation, NOT Unity/backend shader compilation or
GPU performance measurement. Report the separately tested shader backends explicitly.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / 'Packages/com.ruccho.texpix/Runtime/Shaders/Texpix.hlsl'
BASELINE_SHA = 'b9533b05902cc64c037aece25bf51b274b6ee99a'
BASE_FUNCTIONS = ['TexpixPixelsPerTexel', 'TexpixInvPixelsPerTexel', 'TexpixTexelIndex',
                  'TexpixAtlasUV', 'TexpixSubPixel', 'TexpixExtractLevel', 'TexpixShade']
NEW_FUNCTIONS = BASE_FUNCTIONS[:5] + ['TexpixResidueScale', 'TexpixExtractLevel',
                  'TexpixPrepareCoverage', 'TexpixPreparedAtlasUV', 'TexpixShadePrepared', 'TexpixShade']

def extract_function(source: str, name: str) -> str:
    m = re.search(r'(?m)^float[234]?\s+' + re.escape(name) + r'\s*\(', source)
    if not m:
        raise ValueError(f'Function not found: {name}')
    begin = source.index('{', m.end())
    depth = 1
    end = begin + 1
    while depth:
        if source[end] == '{': depth += 1
        elif source[end] == '}': depth -= 1
        end += 1
    return source[m.start():end]

def source_functions(source: str, names: list[str]) -> str:
    return '\n\n'.join(extract_function(source, n) for n in names)

PREAMBLE = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
using uint = std::uint32_t;
using std::floor;
float frac(float x) { return x - std::floor(x); }
float step(float edge, float x) { return x >= edge ? 1.0f : 0.0f; }
struct float2 { float x,y; float2(float a,float b):x(a),y(b){} };
struct float4 {
    float x,y,z,w;
    float4(float a,float b,float c,float d):x(a),y(b),z(c),w(d){}
    float4 operator*(float v) const {return {x*v,y*v,z*v,w*v};}
    float4 operator+(float4 b) const {return {x+b.x,y+b.y,z+b.z,w+b.w};}
};
#define TEXPIX_LEVEL_FILL 3.0f
'''
# HLSL unsuffixed float literals have float precision, unlike C++ double literals.
def cpp_float_literals(text: str) -> str:
    return re.sub(r'(?<![\w.])(\d+\.\d+(?:[eE][+-]?\d+)?)(?![\w.])', r'\1f', text)

HARNESS = r'''
static std::uint64_t checks = 0;
static void eq(float a, float b, const char* context) {
    ++checks;
    if (a != b || !std::isfinite(a) || !std::isfinite(b)) {
        std::cerr << context << ": " << a << " != " << b << "\n";
        throw std::runtime_error("Mismatch");
    }
}
static void eq4(float4 a, float4 b, const char* c) {
    eq(a.x,b.x,c); eq(a.y,b.y,c); eq(a.z,b.z,c); eq(a.w,b.w,c);
}
static void check(float sample, float x, float y, float format, float mode,
                  float4 fill, float4 outline) {
    const float2 pos(x,y);
    const float sub = legacy::TexpixSubPixel(pos,format);
    const float before = legacy::TexpixExtractLevel(sample,sub,format);
    eq(before,portable::TexpixExtractLevel(sample,sub,format),"public portable level");
    eq(before,native_bits::TexpixExtractLevel(sample,sub,format),"public native level");
    const float4 prep = portable::TexpixPrepareCoverage(pos,mode,format);
    const float4 expected = legacy::TexpixShade(before,fill,outline,mode);
    eq4(expected,portable::TexpixShadePrepared(sample,prep,fill,outline),"portable coverage");
    eq4(expected,native_bits::TexpixShadePrepared(sample,prep,fill,outline),"native coverage");
    // Include NPOT sizes: center addressing, not raw UV sampling, must be preserved.
    for (int width : {1,7,257,4096}) {
        const float4 ts(1.0f/width,1.0f/113,width,113);
        const float2 oldUV = legacy::TexpixAtlasUV(pos,ts,format);
        const float2 newUV = portable::TexpixPreparedAtlasUV(prep,ts);
        eq(oldUV.x,newUV.x,"center UV x"); eq(oldUV.y,newUV.y,"center UV y");
    }
}
int main() {
    try {
        const float4 fill(0.25f,0.5f,1.0f,0.625f), outline(0.75f,0.125f,0.5f,0.375f);
        for (int format=0; format<2; ++format) {
            const int p = format ? 8 : 4;
            for (int byte=0; byte<256; ++byte) for(int sub=0; sub<p; ++sub) {
                const float sample=byte/255.0f;
                const float expected=format ? ((byte>>sub)&1)*3 : (byte>>(sub*2))&3;
                eq(expected,legacy::TexpixExtractLevel(sample,sub,format),"integer oracle");
                for (int mode=0;mode<3;++mode) for (float offset : {0.0f,0.125f,0.5f,0.875f}) {
                    check(sample,4096.0f+sub+offset,17.5f,format,mode,fill,outline);
                    // Perturb sampled values by substantial fractions of one byte.
                    for (float e : {-0.49f,-0.125f,0.125f,0.49f}) {
                        const float perturbed=std::clamp((byte+e)/255.0f,0.0f,1.0f);
                        check(perturbed,sub+offset,0.0f,format,mode,fill,outline);
                    }
                }
            }
        }
        std::mt19937 rng(0x54455850);
        std::uniform_real_distribution<float> unit(0,1);
        for (int n=0;n<200000;++n) {
            int format=rng()%2, mode=rng()%3, byte=rng()%256;
            const float sample=byte/255.0f;
            float x=unit(rng)*131072.0f, y=unit(rng)*16384.0f;
            if(n%3==0) x=std::nextafter(std::floor(x),std::numeric_limits<float>::infinity());
            if(n%3==1) x=std::nextafter(std::floor(x)+1.0f,0.0f);
            float4 f(unit(rng),unit(rng),unit(rng),unit(rng));
            float4 o(unit(rng),unit(rng),unit(rng),unit(rng));
            check(sample,x,y,format,mode,f,o);
        }
        std::cout << "{\"scalar_assertions\":" << checks
                  << ",\"random_cases\":200000,\"status\":\"PASS\"}\n";
        return 0;
    } catch(const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
}
'''

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, default=Path(__file__).parent/'baseline')
    ap.add_argument('--output', type=Path)
    args=ap.parse_args()
    before=(args.baseline/'Texpix.hlsl').read_text()
    raw=before.encode()
    actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if actual != BASELINE_SHA:
        raise SystemExit(f'Baseline mismatch: {actual}; expected {BASELINE_SHA}')
    after=HEADER.read_text()
    source=PREAMBLE
    source+='\nnamespace legacy {\n'+cpp_float_literals(source_functions(before,BASE_FUNCTIONS))+'\n}\n'
    bodies=cpp_float_literals(source_functions(after,NEW_FUNCTIONS))
    source+='\nnamespace portable {\n'+bodies+'\n}\n'
    source+='\n#define TEXPIX_USE_NATIVE_BITS\nnamespace native_bits {\n'+bodies+'\n}\n#undef TEXPIX_USE_NATIVE_BITS\n'
    source+=HARNESS
    compiler=shutil.which('clang++') or shutil.which('g++')
    if not compiler: raise SystemExit('Install clang++ or g++ to run the actual-source float32 harness.')
    reports=[]
    with tempfile.TemporaryDirectory(prefix='texpix-validation-') as tmp:
        tmp=Path(tmp); (tmp/'validate.cpp').write_text(source)
        for label,flags in [('strict',['-ffp-contract=off']),('contract',['-ffp-contract=fast'])]:
            binary=tmp/label
            cmd=[compiler,'-std=c++17','-O2',*flags,str(tmp/'validate.cpp'),'-o',str(binary)]
            subprocess.run(cmd,check=True,capture_output=True,text=True)
            run=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
            reports.append({'mode':label,'result':json.loads(run.stdout),'flags':flags})
    report={'baseline_git_blob':actual,'candidate_sha256':hashlib.sha256(after.encode()).hexdigest(),
            'compiler':subprocess.check_output([compiler,'--version'],text=True).splitlines()[0],
            'validation_scope':'C++ translation of actual HLSL function bodies; not Unity or GPU',
            'runs':reports}
    result=json.dumps(report,indent=2)
    print(result)
    if args.output: args.output.write_text(result+'\n')

if __name__=='__main__': main()

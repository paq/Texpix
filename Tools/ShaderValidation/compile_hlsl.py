#!/usr/bin/env python3
"""Compile actual HLSL helpers with glslang and validate the emitted SPIR-V.

Requires glslangValidator, spirv-val, spirv-opt and spirv-dis. This checks the
HLSL helper functions through minimal stage wrappers, NOT Unity's ShaderLab,
Unity's target-2.0 compiler, UI includes, or target GPU ISA/performance.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from validate import HEADER, BASELINE_SHA

HERE = Path(__file__).resolve().parent
COMMON = r'''
Texture2D<float4> atlas : register(t0);
SamplerState atlasSampler : register(s0);
cbuffer Constants : register(b0) {
    float4 atlasTexelSize;
    float4 clipRect;
    float alwaysGammaSpace;
};
struct Input {
    float4 position : POSITION;
    float4 color : COLOR0;
    float4 uv : TEXCOORD0;
};
struct Varyings {
    float4 position : SV_Position;
    float4 data : TEXCOORD0;
    float4 color : TEXCOORD1;
    float4 outline : TEXCOORD2;
    float2 mask : TEXCOORD3;
};
'''
VERTEX = r'''
Varyings main(Input v) {
    Varyings o;
    o.position = v.position;
    float4 outline;
    float mode, format;
    TexpixUnpackOutline(v.uv.zw, outline, mode, format);
    o.data = PAYLOAD;
    o.outline = outline;
    o.color = TexpixUIVertexColor(v.color, alwaysGammaSpace);
    o.mask = v.position.xy;
    return o;
}
'''


def run(command: list[str]) -> str:
    process = subprocess.run(command, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError(' '.join(command) + '\n' + process.stdout + process.stderr)
    return process.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE/'results/hlsl-results.json')
    args = parser.parse_args()
    tools = {}
    for name in ['glslangValidator', 'spirv-val', 'spirv-opt', 'spirv-dis']:
        tools[name] = shutil.which(name)
        if not tools[name]:
            raise SystemExit(f'{name} not installed: compilation is NOT_RUN, not a pass')
    baseline = HERE/'baseline/Texpix.hlsl'
    raw = baseline.read_bytes()
    sha = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if sha != BASELINE_SHA:
        raise SystemExit('Frozen baseline checksum mismatch')
    results = []
    with tempfile.TemporaryDirectory(prefix='texpix-hlsl-') as tmp:
        tmp = Path(tmp)
        for kind, clip, alpha, stage in itertools.product(
                ['legacy', 'portable', 'native'], range(2), range(2), ['vert', 'frag']):
            header = baseline if kind == 'legacy' else HEADER
            source = '#define SHADER_TARGET 35\n' if kind == 'native' else '#define SHADER_TARGET 20\n'
            if kind == 'native':
                source += '#define TEXPIX_USE_NATIVE_BITS\n'
            source += '#include "' + header.resolve().as_posix() + '"\n' + COMMON
            if stage == 'vert':
                payload = ('float4(v.uv.xy, mode, format)' if kind == 'legacy'
                           else 'TexpixPrepareCoverage(v.uv.xy, mode, format)')
                source += VERTEX.replace('PAYLOAD', payload)
            else:
                source += 'float4 main(Varyings i) : SV_Target {\n'
                if kind == 'legacy':
                    source += '''
    float raw = atlas.Sample(atlasSampler, TexpixAtlasUV(i.data.xy, atlasTexelSize, i.data.w)).r;
    float level = TexpixExtractLevel(raw, TexpixSubPixel(i.data.xy, i.data.w), i.data.w);
    float4 color = TexpixShade(level, i.color, i.outline, i.data.z);
'''
                else:
                    source += '''
    float raw = atlas.Sample(atlasSampler, TexpixPreparedAtlasUV(i.data, atlasTexelSize)).r;
    float4 color = TexpixShadePrepared(raw, i.data, i.color, i.outline);
'''
                if clip:
                    source += '    float2 m = saturate((clipRect.zw-abs(i.mask))*clipRect.xy); color.a *= m.x*m.y;\n'
                if alpha:
                    source += '    clip(color.a - 0.001);\n'
                source += '    return color;\n}\n'
            name = f'{kind}-{clip}-{alpha}-{stage}'
            path, binary, optimized = tmp/(name+'.hlsl'), tmp/(name+'.spv'), tmp/(name+'.opt.spv')
            path.write_text(source, encoding='utf-8')
            run([tools['glslangValidator'], '-D', '-V', '--auto-map-bindings',
                 '--auto-map-locations', '-S', stage, '-e', 'main', str(path), '-o', str(binary)])
            run([tools['spirv-val'], str(binary)])
            run([tools['spirv-opt'], '-O', str(binary), '-o', str(optimized)])
            run([tools['spirv-val'], str(optimized)])
            disassembly = run([tools['spirv-dis'], str(optimized)])
            counter = Counter()
            in_function = False
            for line in disassembly.splitlines():
                tokens = line.split()
                if 'OpFunction' in tokens:
                    in_function = True
                if in_function:
                    for index, token in enumerate(tokens):
                        if token.startswith('Op'):
                            key = token
                            if token == 'OpExtInst' and index+3 < len(tokens):
                                key += ':'+tokens[index+3]
                            counter[key] += 1
                            break
                if 'OpFunctionEnd' in tokens:
                    in_function = False
            results.append(dict(kind=kind, clip=bool(clip), alphaClip=bool(alpha), stage=stage,
                                optimized_function_instructions=sum(counter.values()),
                                opcodes=dict(sorted(counter.items())), status='PASS'))
    report = dict(scope='Actual HLSL helpers via minimal wrappers -> SPIR-V; NOT Unity/ShaderLab/SM2 validation or hardware GPU ISA',
                  candidate_sha256=hashlib.sha256(HEADER.read_bytes()).hexdigest(),
                  baseline_git_blob=sha, compiler=run([tools['glslangValidator'], '--version']).strip(),
                  modules_validated=len(results), results=results, status='PASS',
                  performance_measurement='NOT_MEASURED: IR instruction counts are not GPU durations')
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

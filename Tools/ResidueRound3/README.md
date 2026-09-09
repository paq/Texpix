# Round 3: format-free UI palette

Baseline: `e55897ddca6259cc8249f0306bcb2c1900f0571c` (round 2, direct color selection).
Tested production commit: `ee98cd376af5f6d69e423b01a7d6101aaa09704a`.
Fast include SHA-256 (UTF-8, LF): `3ef6c956f478dbf738867d46f78e32b8af3d0aec54c7afdb79ad71997bd88684`.

[Successful CI run](https://github.com/paq/Texpix/actions/runs/34299183172),
[job](https://github.com/paq/Texpix/actions/runs/34299183172/job/102302262564),
[generated reports, DXBC and disassembly](https://github.com/paq/Texpix/actions/runs/34299183172/artifacts/10084279872).
`results/ci-summary.json` is a transcription of that job's output, not another test run.

## Transformation

The standard UI palette has a useful redundancy: 1bpp never draws an outline.
Prepare both colors together in the vertex shader:

```text
                    fill slot       alternate slot
2bpp                fill            outline
1bpp                fill            fill
```

Now `.75` can select the fill slot for **both** formats. For 1bpp, residues in
`[.5,.75)` select the alternate slot, but that slot also contains fill. The visibility
threshold remains `.5`, so outside pixels stay transparent. This removes the need
to interpolate a format-dependent fill threshold.

Use the released component for a continuous low-bit selector coordinate instead:

```text
prepared.xy = (fontPixelX / pixelsPerTexel, fontPixelY)
prepared.z  = visibility threshold (unchanged)
prepared.w  = 1bpp ? fontPixelX * .5 : .75
```

The fragment shader starts with `frac(prepared.xw)`. At 1bpp, `frac(prepared.w)<.5`
identifies the even bit within a pair; at 2bpp, the constant `.75` makes that condition
false. This replaces a dependent phase multiply/frac and a format predicate with
parallel fractional coordinates. It does not add a varying component, Canvas channel,
material keyword, texture sample or draw call. The two scalar coordinate fractions
can share one vector DXBC instruction; this is not a claim that native GPU scalar
instruction counts decrease by the same amount.

### Scale identity

Let `x` be a nonnegative font-pixel coordinate, `P` the pixels per texel, and
`k = floor(x) mod P`. The four-entry table selected by `frac(x/P)` gives

$$
a_j = 2^{-2(j+1)}.
$$

At 2bpp, `P=4`, `j=k`, and the doubling predicate is false. Thus the scale is
`2^(-(2*k+2))`, exactly the original scale. At 1bpp, `P=8` and `j=floor(k/2)`.
An even `k` doubles the table entry and an odd `k` does not; both yield `2^(-(k+1))`.
The centered expression `frac((atlasR*255+.5)*scale)` is therefore unchanged.

Only affine, dyadic coordinate scaling is moved into the vertex shader. `frac`
and `floor` stay in the fragment shader. Styles remain constant per primitive.

### Vertex unpacking

`TexpixUnpackUIOutline` extracts the four outline-color channels with parallel
vector floor operations instead of serially removing higher fields. It retains
`floor(packed+.5)`, the color conversion, mode extraction and format extraction.
This offsets the additional vertex palette preparation in the measured wrappers.

## Production scope

`TexpixUIFast.hlsl` is included by `TexpixUI.shader`; the latter calls
`TexpixPrepareUI` and `TexpixSampleUI_Tex2D`. The generic `Texpix.hlsl` is unchanged
from round 2. Its API, generic palette behavior, and custom shaders such as the
Rainbow sample are not switched to the new payload.

Do not feed the fast payload into `TexpixShadePrepared`: its `w` has a different
meaning. Do not copy this specialization into a shader that changes only the fill
color in the fragment stage: at 1bpp the alternate slot must change identically.
Both candidate colors must remain consistent across vertex interpolation.

Texel-center addressing, R8 encoding, the input mesh layout, straight-alpha blending,
clip ordering and the default shader's target 2.0 declaration are unchanged.
Retaining that declaration is not an actual SM2 or Unity compilation test.

## Compiled operation counts

Windows SDK **10.0.26100.0 FXC**, `/O3`, `ps_4_0` / `vs_4_0`; minimal stage wrappers
containing the actual checked-in helper functions. Counts include `ret` but exclude
declarations. These are **DXBC operations, not native ISA or GPU duration**.

| Pixel variant | Round 2 | Round 3 | Change |
|---|---:|---:|---:|
| No clipping | 20 | 17 | -3 |
| Alpha clipping | 24 | 21 | -3 |
| Rect clipping | 26 | 23 | -3 |
| Both | 29 | 26 | -3 |

Pixel results are identical in gamma and linear builds. Temporary DXBC registers
remain 2. The unclipped reduction is 15%, not a measured 15% speedup.

| Vertex build | Round 2 | Round 3 | Temporary registers |
|---|---:|---:|---:|
| Linear | 45 | 43 | 3 -> 5 |
| Gamma | 31 | 28 | 2 -> 3 |

The WARP wrappers use a simplified mask varying and do not contain Unity's full
vertex transform/mask setup. Do not substitute these vertex counts for the previous
Unity-compiled counts. More temporary registers can matter even with fewer operations;
physical registers, occupancy, spills and execution time have not been measured.

### Correction to round-2 SM5 reporting

The old round-2 parser omitted `sample_indexable(texture2d)(...)` because it matched
only bare opcode tokens. The reported SM5 `22 -> 19` should have been `23 -> 20`;
the other SM5 rows were also one instruction low on both sides. The three-instruction
reduction was unaffected. Round 3 splits off the opcode's parenthesized metadata and
has an explicit regression check that counts this sampling operation.

## Executed correctness checks

The CI job runs **actual FXC-compiled HLSL** through D3D11 WARP, a software device.
There is no HLSL-to-GLSL translation or CPU reimplementation in these comparisons.

| Check | Result |
|---|---:|
| Compute probes per color-space build | 566,936 |
| Color-space builds | 2 |
| Fast/reference color mismatches | 0 |
| Parallel/reference outline-unpack mismatches | 0 |
| Independent integer-oracle mismatches | 0 |
| Execution-signature/sample mismatches | 0 |
| Paired raster comparisons | 3,072 |
| RGBA8 channel comparisons | 404,226,048 |
| Raster mismatches | 0 |
| Uniform rendered images | 0 |

Compute probes include all bytes/subpixels, mode codes 0..3, fractional positions,
neighboring float coordinates, +/-0.49-byte perturbations, threshold ULP perturbations,
random packed colors/formats and 100,000 seeded random cases. Each output has a
CPU-checked thread/sample signature, preventing unwritten UAVs or an unbound zero atlas
from passing unnoticed.

Raster pairs cover 256/257-wide R8 textures, both formats, mode codes 0..3, 1/32 quads,
three transforms including perspective, gamma/linear shader conversion paths,
vertex-color conversion flags 0/1, rectangular soft clipping, alpha clipping and
straight-alpha overdraw. Every rendered image is checked for nonuniform output.
Gamma/linear here means shader conversion code paths; the harness target is RGBA8
UNORM, not a complete pair of Unity color-space projects.

Not tested: Unity ShaderLab compilation/import, actual SM2 compilation, Unity's full
soft-mask vertex setup, CanvasRenderer/CanvasGroup, Stencil/Mask integration, XR,
Metal, mobile low-precision interpolation, or hardware performance. These remain
release gates, not reasons to treat the passing software checks as hardware timings.

## Why not the 16-operation candidate?

The experimental replacement `frac(atlasR * (255.5 * scale))` removes one operation,
but its bias depends on the byte rather than being a constant half-byte. It loses
the original error margin. For the low 2-bit field of `B=4` (outside), use the input
`atlasR=(4-.01)/255` and `scale=.25`:

```text
centered:       frac((3.99 + .5) / 4)       = .1225...  -> outside
proportional:   frac((3.99 / 255) * 63.875) = .999456... -> fill
```

This arithmetic counterexample was also reproduced with per-operation float32
rounding. It is a robustness counterexample under an explicit perturbation, not a
claim that a conformant R8 fetch normally makes an error of that size. The selected
production path keeps `+.5`. The `floor`-to-shared-`frac` addressing experiment did
not improve the selected instruction count, so the original center addressing stays.

## Reproduce on Windows

Use an x64 MSVC Developer Command Prompt with Python 3 and Windows SDK FXC installed.
Adjust the FXC path to the installed SDK:

```bat
set "FXC=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\fxc.exe"
python -X utf8 Tools\ResidueRound3\warp_sources.py --fxc "%FXC%" --output round3-results
cl /nologo /std:c++17 /EHsc /O2 Tools\ResidueRound3\warp.cpp /Fe:round3-results\warp.exe /link d3d11.lib
round3-results\warp.exe round3-results
```

`warp_sources.py` asserts that the generic baseline has not changed and the default
UI source calls the tested fast helpers. For the rejected/alternative formulations:

```bat
python -X utf8 Tools\ResidueRound3\experiment.py --fxc "%FXC%" --output round3-experiments
```

The alternative-formulation sweep compiles candidates; compilation alone does not
certify their correctness. Only the selected centered-palette path receives the
paired WARP validation above. Both scripts preserve generated source, DXBC and
assembly for inspection.

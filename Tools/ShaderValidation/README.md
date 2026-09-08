# Centered Residue Coverage: Texpix shader optimization

Baseline: `paq/Texpix` main `32bb76c2c10de3b69e4a6cb492025380b3883f1a`.
Tested implementation: `80e57df3ec60d2421ce9d1a314a569c203150145`.
Candidate HLSL SHA-256 (LF checkout): `b3167ada5df323f73a532ff26c98840e4d8ea0c99e4e72bbe87fa495b9097c07`.

This change derives and implements a fused decode/shading path. Its numerical tests,
HLSL helper compilation and software-raster comparisons pass in GitHub Actions.
It is **not a measured hardware speedup or a world-fastest claim**. The descriptive
name does not establish historical or patent novelty. No hardware timing has been obtained.

## What changed

The old fragment path reconstructs an integer byte, performs three conditional
floating-point right-shift stages, extracts a 1/2-bit level, and then classifies that
level into fill/outline/outside. The new default path never materializes the level:
it computes one centered residue from the sampled value, then compares it against
two thresholds prepared by the vertex shader.

`TexpixPrepareCoverage` moves format-dependent x scaling and outline-mode decisions
to the vertex stage. Its float4 replaces the existing float4 interpolator, without
changing the input mesh's uv0 layout. `TexpixShadePrepared` performs the direct
classification. The old public functions and macros remain available; custom shaders
using `TexpixExtractLevel` receive the shorter decoder without changing their source.
Format predicates remain boolean instead of being materialized as float 0/1 values
and then compared again. This removes redundant instructions in the tested compiler.

R8 layout, 1bpp/2bpp encoding, packed outline colors, material properties, batching,
mesh construction, draw order, texture count and draw count are unchanged. The default
shader retains `#pragma target 2.0`. Integer decoding is an opt-in comparison path,
not an automatic replacement for the portable path. No additional Canvas channels,
texture lookups, compute shaders, render targets, or material keywords are required.
The optional mask interpolator is explicitly excluded when rectangle clipping is off.
The atlas preview shares one center-addressed fetch between raw and decoded views
instead of having two source-level sampling sites.

## Derivation

Let B be an integer byte, b the bits per font pixel (1 or 2), R = 2^b, and s the
starting bit. Decompose B as

    B = H * (R * 2^s) + L * 2^s + T,
    0 <= L < R, 0 <= T < 2^s.

Then

    r = frac((B + 0.5) / (R * 2^s))
      = L/R + (T + 0.5)/(R * 2^s),
    L/R < r < (L + 1)/R.

Consequently `floor(R*r)` is exactly the required bit field. More importantly, its
integer value is unnecessary when the consumer only tests thresholds. At 2bpp,
`r >= 0.75` means fill, `r >= 0.5` includes edge outlines, and `r >= 0.25` also includes
diagonal outlines. At 1bpp, `r >= 0.5` means fill and both visibility/fill thresholds
are identical, so outline contribution is zero.

| Format / outline mode | Visible threshold | Fill threshold |
|---|---:|---:|
| 2bpp / none | 0.75 | 0.75 |
| 2bpp / four-neighbor | 0.50 | 0.75 |
| 2bpp / eight-neighbor | 0.25 | 0.75 |
| 1bpp / any | 0.50 | 0.50 |

The final color is

    fillMask = step(fillThreshold, r);
    outlineMask = step(visibleThreshold, r) - fillMask;
    color = fillColor * fillMask + outlineColor * outlineMask;

Masks are disjoint. The expression preserves straight-alpha selection rather than
introducing a subtractive lerp, premultiplication or early discard. The existing UI
soft-mask multiplication, alpha clipping and blending remain in their original order.

The implementation selects exact dyadic constants, not approximate division or exp2.
`B+0.5` is evaluated as `atlasR*255+0.5`; the byte-rounding floor is unnecessary.
If the reconstructed sample is B+epsilon with |epsilon| < 0.5, the strict interval
above still holds in real arithmetic. Float32 rounding and backend behavior remain
separate validation questions. The smallest ideal distance to a bucket boundary is
1/512. Keep decode values and coordinates in float, never half/fixed. Center-addressed
texture sampling is retained; raw interpolated UVs are not substituted in the UI path.

For continuous font coordinate x and P font pixels per texel, floor(floor(x)/P) equals
floor(x/P) for the supported nonnegative coordinates. Since P is 4 or 8, the affine
power-of-two transform can be applied before interpolation. Nonlinear floor/frac
operations stay in the fragment stage. Format and mode must be constant per primitive,
as they are for Texpix glyph quads; arbitrary interpolated style values are not a
supported new input contract.

## Executed validation

The final implementation was tested by [GitHub Actions run 34272601873](https://github.com/paq/Texpix/actions/runs/34272601873).
The checked-in CPU and GLSL reports are copied from that run's generated output;
`results/ci-summary.json` records the tested commit, provenance and IR count summary.
The run artifact contains the full HLSL opcode report and generated standalone HTML.
The first CI attempt exposed an absolute-include-path issue in the compiler harness;
it was fixed by inlining the exact header, and all checks were subsequently rerun.

| Test | Executed result |
|---|---|
| Actual helper bodies translated to C++ float32, Clang 18.1.3, contraction off | 8,100,480 scalar assertions passed |
| Same source, contraction permitted | 8,100,480 scalar assertions passed |
| Actual HLSL helpers, glslang 15.1.0, SPIR-V validation before/after optimization | 24 modules passed |
| Mesa GLSL ES 3.00 compile/link | 12 program pairs linked |
| Mesa GLSL ES 1.00 compile | 16 individual shaders compiled |
| Mesa/llvmpipe rendered comparisons | 576 comparisons, 303,169,536 RGBA8 channels, zero differences |
| Standalone browser lab generation | Passed; browser execution not performed |
| Unity compiler/Test Runner | Not executed |
| Real hardware GPU timing | Not measured |

The scalar checks cover every byte and subpixel, both formats, all outline modes,
subpixel positions, +/-0.49-byte sample perturbations, independently perturbed threshold
ULPs, NPOT addressing, and 200,000 seeded random cases per compiler configuration.
Allowing FP contraction is not evidence that FMA instructions were actually executed.
The raster tests cover POT/NPOT R8 textures (256/257 texels wide), varying vertex colors,
translucent overdraw, rectangular soft clipping, alpha clipping, fractional positions,
rotation and perspective interpolation. Rendering used llvmpipe (LLVM 20.1.2) on
Mesa 25.2.8, not a hardware GPU; the renderer identifies itself in the report.

HLSL compilation uses the complete unmodified header with minimal vertex/fragment
wrappers. This verifies HLSL syntax and valid SPIR-V, not Unity's ShaderLab, includes,
real shader-model-2 compilation, or target GPU ISA. The GLSL raster harness mechanically
translates the actual helper bodies; it is a separate compiler path, not execution
of the HLSL-generated SPIR-V. These distinctions are intentional.

These checks do not exercise CanvasRenderer, Stencil/Mask, XR, gamma/linear project
settings, CanvasGroup behavior, the editor atlas preview or arbitrary custom user
shaders. The browser's GLSL source was exercised through Mesa/EGL, not a browser;
the browser timer path has not been hardware-validated here.

The package includes `TexpixShaderTests`: 24 Unity GPU probe cases comparing level/color
to an integer oracle, plus 4 UI keyword-variant bind checks. These are supplied but
unrun. Skipping tests because no graphics device is available is not a pass.

## Compiler evidence, not GPU timings

The actual HLSL stage wrappers were compiled using glslang 15.1.0, optimized with
`spirv-opt -O`, validated with `spirv-val`, and disassembled with `spirv-dis`.
The following are instruction counts inside optimized SPIR-V functions, including
loads/stores, composite operations and function boundaries. They are not native GPU
instruction counts, cycle counts or measured speedups.

| Stage / clipping | Baseline | Portable residue | Optional native bits |
|---|---:|---:|---:|
| Vertex, all test variants | 81 | 90 | 90 |
| Fragment, neither clip | 79 | 52 | 50 |
| Fragment, alpha clip | 87 | 60 | 58 |
| Fragment, rectangle clip | 94 | 67 | 65 |
| Fragment, both clips | 101 | 74 | 72 |

The unclipped portable fragment has 27 fewer IR instructions (34.2% fewer), but the
vertex stage has 9 more. There is still one texture sample. The portable fragment's
9 explicit Floor operations become 2 Floor plus 3 Fract operations; how those map to
hardware instructions is backend-dependent. Integer extraction is slightly smaller
in this IR, but introduces float/integer conversions and need not be faster on a GPU.
No hardware speedup percentage is inferred from this table.

## Reproduce

From the repository root (Python 3.9+; `-X utf8` also handles Japanese Windows locales):

```sh
python -X utf8 Tools/ShaderValidation/validate.py
python -X utf8 Tools/ShaderValidation/compile_hlsl.py
python -X utf8 Tools/ShaderValidation/gpu_lab.py --html texpix_shader_lab.html
```

The first command needs clang++ or g++. The second needs glslangValidator and SPIR-V
Tools (spirv-val, spirv-opt, spirv-dis). Open the generated HTML in a WebGL2 browser
to run the differential comparisons and hardware timer experiment. On Linux with
NumPy, libEGL and libGL installed, the software raster check is:

```sh
python -X utf8 Tools/ShaderValidation/run_egl.py
```

The local `.gitattributes` preserves the frozen baseline's LF bytes on checkout.
In Unity 6000.3+, run the EditMode fixture `Texpix.Tests.TexpixShaderTests` with an actual
graphics device, not `-nographics`. Also run the existing package tests and visual
regression scenes on D3D11 and Metal before merging.

To benchmark the optional integer helper path in a compatible custom shader, set
these before including `Texpix.hlsl`:

```hlsl
#pragma target 3.5
#define TEXPIX_USE_NATIVE_BITS
```

Unity's target 3.5 includes native integer/bit operations. The default shader is not
silently promoted to this target. Neither variant should be declared universally
faster on the basis of source operation counts.

## Hardware performance acceptance

The lab compares old/portable/native helpers, with the same atlas and output size,
after correctness checks and warm-up. It offers one large rectangle versus 4,096
small rectangles, 1bpp versus 2bpp, and blending on/off. GPU timer queries record raw
samples plus median/p10/p90; software-renderer, unavailable-timer, invalid-query and
disjoint-clock cases do not produce a claimed speedup.

This remains a synthetic cached-atlas workload, not a representative Unity scene.
For a release decision, compare identical Unity scenes at pixel scales 1/2/4/8 and
small/dense text populations, with all outline modes, clipping, overlapping translucent
text, and multiple atlases. Record actual GPU duration, CPU Canvas rebuild cost,
variant ISA, registers, spills, occupancy and texture/ROP pressure on each target GPU.
Moving work to vertices can lose on tiny glyphs; fewer ALU operations can be hidden by
texture or blending bottlenecks. Choose the default using those measurements.

Further candidates deliberately not made default: native Texture.Load with explicitly
preserved clamp semantics, format-specialized shaders if they do not damage batching,
and overdraw-reducing geometry outside this shader-only change. Texture expansion,
LUT fetches, unconditional alpha discard, unsafe half precision, and approximate
exp2/reciprocal decoding are not used to claim an unmeasured win.

## References

- Frozen source: `baseline/Texpix.hlsl` (MIT notice in `baseline/LICENSE`).
- Verified CI: https://github.com/paq/Texpix/actions/runs/34272601873
- Unity target reference: https://docs.unity3d.com/6000.3/Documentation/Manual/SL-Pragma-target.html
- HLSL frac: https://learn.microsoft.com/en-us/windows/win32/direct3dhlsl/dx-graphics-hlsl-frac
- GPU timer extension: https://registry.khronos.org/webgl/extensions/EXT_disjoint_timer_query_webgl2/

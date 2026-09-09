// Default-UI specialization. Keep Texpix.hlsl for custom fragment-stage palettes.
#ifndef TEXPIX_UI_FAST_INCLUDED
#define TEXPIX_UI_FAST_INCLUDED
#include "Texpix.hlsl"

// Decode all four color channels in parallel instead of subtracting fields serially.
// The input is TexpixVertexFormat's packed integer pair. Retain its rounding step.
void TexpixUnpackUIOutline(float2 packed, out float4 color, out float mode, out float format)
{
    packed = floor(packed + 0.5);
    float4 q = floor(packed.xxyy * float4(0.00390625, 1.0, 0.0009765625, 0.25));
    float4 high = floor(q * 0.00390625);
    float4 channels = (q - high * 256.0) * (1.0 / 255.0);
    format = high.z;
    mode = packed.y - q.w * 4.0;
    color = float4(TexpixUIGammaToWorkingSpace(channels.xyz), channels.w);
}

// Prepare coordinates AND the palette together. Do not use this payload with
// TexpixShadePrepared: its w component has a different meaning.
//
// 1bpp never needs an outline color. Put fill into both palette entries, making
// the fill-choice threshold .75 for both formats. Visibility still uses .5 for
// 1bpp, so a set bit selects fill even when its residue is below .75.
//
// Reuse the former fill-threshold component for an affine low-bit selector:
//   1bpp: fontPx.x / 2 (frac < .5 selects the even bit of a pair)
//   2bpp: .75           (frac < .5 is always false)
// This removes the fragment format predicate and its dependent phase multiply.
// Keep this coordinate in float, and keep style constant per primitive.
void TexpixPrepareUI(float4 texcoord, float4 vertexColor, float alwaysGammaSpace,
                     out float4 prepared, out float4 fillColor, out float4 alternateColor)
{
    float4 outline;
    float mode, format;
    TexpixUnpackUIOutline(texcoord.zw, outline, mode, format);
    bool fillOnly = format >= 0.5;
    fillColor = TexpixUIVertexColor(vertexColor, alwaysGammaSpace);
    alternateColor = fillOnly ? fillColor : outline;
    float visible = mode >= 1.5 ? 0.25 : (mode >= 0.5 ? 0.5 : 0.75);
    prepared = float4(texcoord.x * (fillOnly ? 0.125 : 0.25), texcoord.y,
                      fillOnly ? 0.5 : visible, fillOnly ? texcoord.x * 0.5 : 0.75);
}

float4 TexpixShadeUI(float atlasR, float4 prepared, float4 fillColor, float4 alternateColor)
{
    float2 phase = frac(prepared.xw);
    float scale = phase.x < 0.5
        ? (phase.x < 0.25 ? 0.25 : 0.0625)
        : (phase.x < 0.75 ? 0.015625 : 0.00390625);
    scale *= phase.y < 0.5 ? 2.0 : 1.0;
    // Preserve centered bias and the original sample-error margin.
    float residue = frac((atlasR * 255.0 + 0.5) * scale);
    float4 selected = residue >= 0.75 ? fillColor : alternateColor;
    return residue >= prepared.z ? selected : float4(0.0, 0.0, 0.0, 0.0);
}

// Point sample at the same texel center as the existing path. No early discard.
#define TexpixSampleUI_Tex2D(tex, texelSize, prepared, fillColor, alternateColor) \
    TexpixShadeUI(tex2D((tex), TexpixPreparedAtlasUV((prepared), (texelSize))).r, \
                  (prepared), (fillColor), (alternateColor))
#endif

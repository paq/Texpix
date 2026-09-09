// Experimental alternatives to TexpixShadePrepared, baseline b990a3f.
// R8 atlas data and the existing prepared float4 are unchanged.
// Finite colors, point-sampled linear R8 and valid prepared inputs are required.
// No hardware GPU speedup is implied by this experiment.

float4 TexpixSelectCoverage(float residue, float4 prepared, float4 fillColor, float4 outlineColor)
{
    float4 selected = residue >= prepared.w ? fillColor : outlineColor;
    return residue >= prepared.z ? selected : float4(0.0, 0.0, 0.0, 0.0);
}

// Fold the byte affine transform into the coefficient lookup.
float2 TexpixResidueAffine(float phase, bool fillOnly)
{
    float2 c = phase < 0.5
        ? (phase < 0.25 ? float2(63.75, 0.125) : float2(15.9375, 0.03125))
        : (phase < 0.75 ? float2(3.984375, 0.0078125) : float2(0.99609375, 0.001953125));
    return c * ((fillOnly && frac(phase * 4.0) < 0.5) ? 2.0 : 1.0);
}

// Factor the four-entry scale into independent binary decisions.
float TexpixResidueProduct(float atlasR, float texelX, bool fillOnly)
{
    float3 phase = frac(float3(texelX, texelX * 2.0, texelX * 4.0));
    float a = phase.x < 0.5 ? 0.25 : 0.015625;
    float b = phase.y < 0.5 ? 1.0 : 0.25;
    float c = (fillOnly && phase.z < 0.5) ? 2.0 : 1.0;
    return frac((atlasR * 255.0 + 0.5) * ((a * b) * c));
}

float TexpixResidueProductAffine(float atlasR, float texelX, bool fillOnly)
{
    float3 phase = frac(float3(texelX, texelX * 2.0, texelX * 4.0));
    float2 c = phase.x < 0.5 ? float2(63.75, 0.125) : float2(3.984375, 0.0078125);
    float b = phase.y < 0.5 ? 1.0 : 0.25;
    float d = (fillOnly && phase.z < 0.5) ? 2.0 : 1.0;
    c *= b * d;
    return frac(atlasR * c.x + c.y);
}

float4 TexpixShadeCandidate(float atlasR, float4 prepared, float4 fillColor, float4 outlineColor)
{
#if EXPERIMENT == 0
    return TexpixShadePrepared(atlasR, prepared, fillColor, outlineColor);
#else
    bool fillOnly = prepared.w < 0.625;
#if EXPERIMENT == 1
    float phase = frac(prepared.x);
    float residue = frac((atlasR * 255.0 + 0.5) * TexpixResidueScale(phase, fillOnly));
#elif EXPERIMENT == 2
    float2 c = TexpixResidueAffine(frac(prepared.x), fillOnly);
    float residue = frac(atlasR * c.x + c.y);
#elif EXPERIMENT == 3
    float residue = TexpixResidueProduct(atlasR, prepared.x, fillOnly);
#elif EXPERIMENT == 4
    float residue = TexpixResidueProductAffine(atlasR, prepared.x, fillOnly);
#elif EXPERIMENT == 5
    float2 p = frac(float2(prepared.x, prepared.x * 4.0));
    float2 c = p.x < 0.5
        ? (p.x < 0.25 ? float2(63.75, 0.125) : float2(15.9375, 0.03125))
        : (p.x < 0.75 ? float2(3.984375, 0.0078125) : float2(0.99609375, 0.001953125));
    c *= ((fillOnly && p.y < 0.5) ? 2.0 : 1.0);
    float residue = frac(atlasR * c.x + c.y);
#elif EXPERIMENT == 6
    float2 p = frac(float2(prepared.x, prepared.x * 4.0));
    float scale = p.x < 0.5
        ? (p.x < 0.25 ? 0.25 : 0.0625)
        : (p.x < 0.75 ? 0.015625 : 0.00390625);
    scale *= ((fillOnly && p.y < 0.5) ? 2.0 : 1.0);
    float residue = frac((atlasR * 255.0 + 0.5) * scale);
#endif
    return TexpixSelectCoverage(residue, prepared, fillColor, outlineColor);
#endif
}

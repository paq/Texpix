// Round-3 experiments. Most combinations are deliberately not production code.
// R3_TABLE: 0=nested constants, 1=prefix-dot lookup.
// R3_BIAS: 0=centered (+.5), 1=sample-proportional bias (weaker error margin).
// R3_PAYLOAD: 0=existing, 1=signed threshold (boundary-sensitive), 2=vertex palette.
// R3_ADDRESS: 0=floor center, 1=share xy fractional parts with center addressing.

void R3Unpack(float2 packed, out float4 color, out float mode, out float format)
{
#if R3_UNPACK
    packed = floor(packed + 0.5);
    float4 q = floor(packed.xxyy * float4(0.00390625, 1.0, 0.0009765625, 0.25));
    float4 high = floor(q * 0.00390625);
    float4 channels = (q - high * 256.0) * (1.0 / 255.0);
    format = high.z;
    mode = packed.y - q.w * 4.0;
    color = float4(TexpixUIGammaToWorkingSpace(channels.xyz), channels.w);
#else
    TexpixUnpackOutline(packed, color, mode, format);
#endif
}

float4 R3Prepare(float2 fontPx, float mode, float format)
{
    float4 p = TexpixPrepareCoverage(fontPx, mode, format);
#if R3_PAYLOAD == 1
    p.w = format >= 0.5 ? -0.5 : 0.75;
#elif R3_PAYLOAD == 2
    // The outline palette is replaced by fill at the vertex for 1bpp.
    // Then the fill threshold can be the constant .75 for BOTH formats.
    // The released w component carries a periodic bit selector instead.
    p.w = format >= 0.5 ? fontPx.x * 0.5 : 0.75;
#endif
    return p;
}

float4 R3Outline(float format, float4 fill, float4 outline)
{
#if R3_PAYLOAD == 2
    return format >= 0.5 ? fill : outline;
#else
    return outline;
#endif
}

float R3Scale(float phase, bool doubleScale)
{
#if R3_TABLE
    float4 before = (float4)(phase < float4(0.25, 0.5, 0.75, 1.0));
#if R3_BIAS
    float scale = dot(before, float4(47.90625, 11.9765625, 2.994140625, 0.998046875));
#else
    float scale = dot(before, float4(0.1875, 0.046875, 0.01171875, 0.00390625));
#endif
#else
#if R3_BIAS
    float scale = phase < 0.5
        ? (phase < 0.25 ? 63.875 : 15.96875)
        : (phase < 0.75 ? 3.9921875 : 0.998046875);
#else
    float scale = phase < 0.5
        ? (phase < 0.25 ? 0.25 : 0.0625)
        : (phase < 0.75 ? 0.015625 : 0.00390625);
#endif
#endif
    return scale * (doubleScale ? 2.0 : 1.0);
}

float4 R3Shade(float raw, float4 p, float4 fill, float4 outline)
{
    float phase = frac(p.x);
#if R3_PAYLOAD == 1
    bool doubleScale = frac(phase * 4.0) < -p.w;
#elif R3_PAYLOAD == 2
    bool doubleScale = frac(p.w) < 0.5;
#else
    bool doubleScale = p.w < 0.625 && frac(phase * 4.0) < 0.5;
#endif
    float scale = R3Scale(phase, doubleScale);
#if R3_BIAS
    // raw * 255.5 = B + B/510 for an ideal B/255 sample.
    float residue = frac(raw * scale);
#else
    float residue = frac((raw * 255.0 + 0.5) * scale);
#endif
#if R3_PAYLOAD == 2
    float4 selected = residue >= 0.75 ? fill : outline;
#else
    float4 selected = residue >= p.w ? fill : outline;
#endif
    return residue >= p.z ? selected : float4(0.0, 0.0, 0.0, 0.0);
}

float2 R3UV(float4 p, float4 ts)
{
#if R3_ADDRESS
    float2 phase = frac(p.xy);
    return (p.xy - phase + 0.5) * ts.xy;
#else
    return TexpixPreparedAtlasUV(p, ts);
#endif
}

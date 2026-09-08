#include "UnityCG.cginc"
#include "../../Runtime/Shaders/Texpix.hlsl"

sampler2D _MainTex;
float4 _MainTex_TexelSize;
float _AtlasFormat;
float _OutlineMode;
float _Probe;
float4 _Fill;
float4 _Outline;

struct ProbeVaryings
{
    float4 vertex : SV_POSITION;
    float2 fontPx : TEXCOORD0;
    float4 prepared : TEXCOORD1;
};

ProbeVaryings vert(appdata_img v)
{
    ProbeVaryings o;
    o.vertex = UnityObjectToClipPos(v.vertex);
    // Each row is identical; texture/RT vertical orientation cannot hide a decode error.
    o.fontPx = float2(v.texcoord.x * 256.0 * TexpixPixelsPerTexel(_AtlasFormat), 0.5);
    o.prepared = TexpixPrepareCoverage(o.fontPx, _OutlineMode, _AtlasFormat);
    return o;
}

float4 frag(ProbeVaryings i) : SV_Target
{
    // Both sample sites remain outside dynamic flow control, including the SM2 pass.
    float level = TexpixSampleLevel_Tex2D(_MainTex, _MainTex_TexelSize, i.fontPx, _AtlasFormat);
    float4 shaded = TexpixSampleCoverage_Tex2D(_MainTex, _MainTex_TexelSize, i.prepared, _Fill, _Outline);
    return _Probe < 0.5 ? float4(level / 3.0, level / 3.0, level / 3.0, 1.0) : shaded;
}

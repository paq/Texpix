Shader "Hidden/Texpix/Shader Probe"
{
    Properties { _MainTex ("Atlas", 2D) = "black" {} }
    SubShader
    {
        Cull Off ZWrite Off ZTest Always Blend Off
        Pass
        {
            Name "Portable"
            CGPROGRAM
            #pragma target 2.0
            #pragma vertex vert
            #pragma fragment frag
            #include "TexpixShaderProbe.hlsl"
            ENDCG
        }
        Pass
        {
            Name "NativeBits"
            CGPROGRAM
            #pragma target 3.5
            #pragma vertex vert
            #pragma fragment frag
            #define TEXPIX_USE_NATIVE_BITS
            #include "TexpixShaderProbe.hlsl"
            ENDCG
        }
    }
}

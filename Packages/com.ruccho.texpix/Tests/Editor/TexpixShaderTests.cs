using System.Collections.Generic;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace Texpix.Tests
{
    // These are real Unity/backend tests, not the standalone C++/GLSL oracle tests.
    // Run in an Editor with a graphics device, not -nographics. A skip is NOT a pass.
    public class TexpixShaderTests
    {
        private static IEnumerable<TestCaseData> DecodeCases()
        {
            for (var format = 0; format < 2; format++)
            for (var mode = 0; mode < 3; mode++)
            for (var pass = 0; pass < 2; pass++)
            for (var probe = 0; probe < 2; probe++)
                yield return new TestCaseData(format, mode, pass, probe)
                    .SetName($"ShaderDecode_Format{format}_Mode{mode}_Pass{pass}_Probe{probe}");
        }

        [TestCaseSource(nameof(DecodeCases))]
        public void EveryPackedByte_MatchesIntegerOracle(int format, int mode, int pass, int probe)
        {
            RequireGraphicsDevice();
            if (pass == 1 && SystemInfo.graphicsShaderLevel < 35)
                Assert.Ignore("Native-bit probe requires shader target 3.5.");
            if (!SystemInfo.SupportsTextureFormat(TextureFormat.R8))
                Assert.Ignore("The graphics device does not support the R8 atlas format.");

            var shader = Shader.Find("Hidden/Texpix/Shader Probe");
            Assert.IsNotNull(shader, "Shader probe was not imported.");
            Assert.IsFalse(ShaderUtil.ShaderHasError(shader), "Probe shader has compilation errors.");
            var material = new Material(shader);
            Texture2D atlas = null;
            Texture2D readback = null;
            RenderTexture target = null;
            var previous = RenderTexture.active;
            var previousSrgb = GL.sRGBWrite;
            try
            {
                atlas = new Texture2D(256, 1, TextureFormat.R8, false, true)
                {
                    filterMode = FilterMode.Point,
                    wrapMode = TextureWrapMode.Clamp
                };
                var bytes = new byte[256];
                for (var i = 0; i < bytes.Length; i++) bytes[i] = (byte)i;
                atlas.LoadRawTextureData(bytes);
                atlas.Apply(false, false);

                var pixelsPerTexel = format == 1 ? 8 : 4;
                var width = 256 * pixelsPerTexel;
                target = RenderTexture.GetTemporary(width, 1, 0,
                    RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
                readback = new Texture2D(width, 1, TextureFormat.RGBA32, false, true);
                var fill = new Color32(32, 128, 240, 160);
                var outline = new Color32(224, 48, 80, 96);
                material.SetFloat("_AtlasFormat", format);
                material.SetFloat("_OutlineMode", mode);
                material.SetFloat("_Probe", probe);
                material.SetVector("_Fill", (Color)fill);
                material.SetVector("_Outline", (Color)outline);
                GL.sRGBWrite = false;
                Graphics.Blit(atlas, target, material, pass);
                Assert.IsFalse(ShaderUtil.ShaderHasError(shader), "Backend compilation failed.");
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, width, 1), 0, 0, false);
                readback.Apply(false, false);
                var actual = readback.GetPixels32();
                for (var x = 0; x < width; x++)
                {
                    var packed = x / pixelsPerTexel;
                    var sub = x % pixelsPerTexel;
                    var level = format == 1 ? ((packed >> sub) & 1) * 3 : (packed >> (2 * sub)) & 3;
                    Color32 expected;
                    if (probe == 0)
                    {
                        var l = (byte)(level * 85);
                        expected = new Color32(l, l, l, 255);
                    }
                    else
                    {
                        var visible = mode == 2 ? level >= 1 : mode == 1 && level >= 2;
                        expected = level == 3 ? fill : visible ? outline : new Color32(0, 0, 0, 0);
                    }
                    var a = actual[x];
                    // Permit one UNorm conversion LSB, never a classification mismatch.
                    var ok = Mathf.Abs(a.r - expected.r) <= 1 && Mathf.Abs(a.g - expected.g) <= 1 &&
                             Mathf.Abs(a.b - expected.b) <= 1 && Mathf.Abs(a.a - expected.a) <= 1;
                    Assert.IsTrue(ok, $"byte={packed}, sub={sub}, expected={expected}, actual={a}");
                }
            }
            finally
            {
                GL.sRGBWrite = previousSrgb;
                RenderTexture.active = previous;
                if (target != null) RenderTexture.ReleaseTemporary(target);
                if (atlas != null) Object.DestroyImmediate(atlas);
                if (readback != null) Object.DestroyImmediate(readback);
                Object.DestroyImmediate(material);
            }
        }

        [TestCase(false, false)]
        [TestCase(true, false)]
        [TestCase(false, true)]
        [TestCase(true, true)]
        public void DefaultShader_UiKeywordVariantsBind(bool clipRect, bool alphaClip)
        {
            RequireGraphicsDevice();
            var shader = Shader.Find("Texpix/UI Default");
            Assert.IsNotNull(shader);
            var material = new Material(shader);
            try
            {
                if (clipRect) material.EnableKeyword("UNITY_UI_CLIP_RECT");
                if (alphaClip) material.EnableKeyword("UNITY_UI_ALPHACLIP");
                Assert.IsTrue(material.SetPass(0), "The selected UI variant could not bind.");
                Assert.IsFalse(ShaderUtil.ShaderHasError(shader));
            }
            finally { Object.DestroyImmediate(material); }
        }

        private static void RequireGraphicsDevice()
        {
            if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
                Assert.Ignore("A real graphics device is required; do not run with -nographics.");
        }
    }
}

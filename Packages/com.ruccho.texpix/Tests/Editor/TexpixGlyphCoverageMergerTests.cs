using System;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

namespace Texpix.Tests
{
    public class TexpixGlyphCoverageMergerTests
    {
        [Test]
        public void UnifiedOutline_IsOptInAndChangesGeneratedMesh()
        {
            var osFont = Font.CreateDynamicFontFromOSFont("Arial", 16);
            if (osFont == null)
            {
                Assert.Ignore("Arial not available on this system.");
                return;
            }

            var fontAsset = TexpixFontAsset.Create(osFont, 16);
            var canvasObject = new GameObject("Texpix unified-outline canvas", typeof(RectTransform),
                typeof(Canvas));
            var textObject = new GameObject("Texpix unified-outline text", typeof(RectTransform),
                typeof(CanvasRenderer), typeof(TexpixText));
            textObject.transform.SetParent(canvasObject.transform, false);
            try
            {
                Assert.That(fontAsset.TryGetGlyph('A', out var glyph), Is.True);

                canvasObject.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
                var text = textObject.GetComponent<TexpixText>();
                Assert.That(text.UnifiedOutline, Is.False);
                text.rectTransform.sizeDelta = new Vector2(256, 64);
                text.Font = fontAsset;
                text.Text = "AA";
                text.LetterSpacing = -glyph.Advance - fontAsset.GetKerning(glyph.GlyphIndex, glyph.GlyphIndex);
                text.OutlineMode = TexpixOutlineMode.FourNeighbor;
                text.OutlineColor = Color.black;

                var regularVertexCount = GetRenderedVertexCount(text);
                text.UnifiedOutline = true;

                Assert.That(GetRenderedVertexCount(text), Is.Not.EqualTo(regularVertexCount));
            }
            finally
            {
                Object.DestroyImmediate(canvasObject);
                Object.DestroyImmediate(fontAsset);
                Object.DestroyImmediate(osFont);
            }
        }

        [Test]
        public void Merge_EmitsEveryCoveredPixelOnceAsAUnitQuad()
        {
            using var atlas = CreateAtlas(out var first, out var second);
            atlas.WriteGlyph(first, new byte[] { 2, 2 }, 2, 1);
            atlas.WriteGlyph(second, new byte[] { 2, 2 }, 2, 1);
            var merged = Merge(atlas, new List<TexpixQuad>
            {
                new()
                {
                    X = 0, Y = 0, Width = 2, Height = 1,
                    AtlasX = first.x, AtlasY = first.y, Color = Color.white
                },
                new()
                {
                    X = 1, Y = 0, Width = 2, Height = 1,
                    AtlasX = second.x, AtlasY = second.y, Color = Color.white
                }
            }, TexpixOutlineMode.FourNeighbor);

            AssertCoverageIsUniqueUnitQuads(merged, 3);
            Assert.That(Covers(merged, 0, 0), Is.True);
            Assert.That(Covers(merged, 1, 0), Is.True);
            Assert.That(Covers(merged, 2, 0), Is.True);
        }

        [Test]
        public void Merge_UsesFillPriorityThenLogicalTextOrder()
        {
            using var atlas = CreateAtlas(out var first, out var second);
            atlas.WriteGlyph(first, new byte[] { 3 }, 1, 1);
            atlas.WriteGlyph(second, new byte[] { 2 }, 1, 1);
            var firstColor = new Color32(12, 34, 56, 78);
            var source = new List<TexpixQuad>
            {
                new()
                {
                    X = 0, Y = 0, Width = 1, Height = 1,
                    AtlasX = first.x, AtlasY = first.y, Color = firstColor
                },
                new()
                {
                    X = 0, Y = 0, Width = 1, Height = 1,
                    AtlasX = second.x, AtlasY = second.y, Color = Color.white
                }
            };

            var merged = Merge(atlas, source, TexpixOutlineMode.FourNeighbor);
            Assert.That(merged, Has.Count.EqualTo(1));
            Assert.That(merged[0].AtlasX, Is.EqualTo(first.x));
            Assert.That(merged[0].Color, Is.EqualTo(firstColor));

            atlas.WriteGlyph(second, new byte[] { 3 }, 1, 1);
            var laterColor = new Color32(200, 100, 50, 128);
            source[1] = new TexpixQuad
            {
                X = 0, Y = 0, Width = 1, Height = 1,
                AtlasX = second.x, AtlasY = second.y, Color = laterColor
            };

            merged = Merge(atlas, source, TexpixOutlineMode.None);
            Assert.That(merged, Has.Count.EqualTo(1));
            Assert.That(merged[0].Color, Is.EqualTo(laterColor));
        }

        [Test]
        public void Merge_RespectsOutlineModeAndFillOnlyFormat()
        {
            using var outlineAtlas = CreateAtlas(out var origin, out _);
            outlineAtlas.WriteGlyph(origin, new byte[] { 1, 2, 3 }, 3, 1);
            var source = new List<TexpixQuad>
            {
                new()
                {
                    X = 0, Y = 0, Width = 3, Height = 1,
                    AtlasX = origin.x, AtlasY = origin.y, Color = Color.white
                }
            };

            Assert.That(Merge(outlineAtlas, source, TexpixOutlineMode.None), Has.Count.EqualTo(1));
            Assert.That(Merge(outlineAtlas, source, TexpixOutlineMode.FourNeighbor), Has.Count.EqualTo(2));
            Assert.That(Merge(outlineAtlas, source, TexpixOutlineMode.EightNeighbor), Has.Count.EqualTo(3));

            using var fillAtlas = new TexpixAtlas(8, 1, 8, 1, 1, TexpixAtlasFormat.FillOnly);
            Assert.That(fillAtlas.TryAllocateCell(out _, out var fillOrigin), Is.True);
            fillAtlas.WriteGlyph(fillOrigin, new byte[] { 1, 0, 1 }, 3, 1);

            var fillMerged = Merge(fillAtlas,
                new List<TexpixQuad>
                {
                    new()
                    {
                        X = 0, Y = 0, Width = 3, Height = 1,
                        AtlasX = fillOrigin.x, AtlasY = fillOrigin.y, Color = Color.white
                    }
                },
                TexpixOutlineMode.EightNeighbor);
            Assert.That(fillMerged, Has.Count.EqualTo(2));
        }

        [Test]
        public void Merge_AssignsFallbackOverlapToOneSource()
        {
            using var primary = new TexpixAtlas(4, 1, 4, 1, 1);
            using var fallback = new TexpixAtlas(4, 1, 4, 1, 1);
            primary.TryAllocateCell(out _, out var primaryOrigin);
            fallback.TryAllocateCell(out _, out var fallbackOrigin);
            primary.WriteGlyph(primaryOrigin, new byte[] { 2 }, 1, 1);
            fallback.WriteGlyph(fallbackOrigin, new byte[] { 2 }, 1, 1);

            var sources = new List<TexpixGlyphAtlasSource>
            {
                new(primary.Texture, TexpixAtlasFormat.Outline),
                new(fallback.Texture, TexpixAtlasFormat.Outline)
            };
            var merged = new List<TexpixQuad>();
            TexpixGlyphCoverageMerger.Merge(sources, new List<TexpixQuad>
            {
                new()
                {
                    X = 0, Y = 0, Width = 1, Height = 1,
                    AtlasX = primaryOrigin.x, AtlasY = primaryOrigin.y, Color = Color.white
                },
                new()
                {
                    X = 0, Y = 0, Width = 1, Height = 1,
                    AtlasX = fallbackOrigin.x, AtlasY = fallbackOrigin.y, Color = Color.white, FontIndex = 1
                }
            }, TexpixOutlineMode.FourNeighbor, merged);

            Assert.That(merged, Has.Count.EqualTo(1));
            Assert.That(merged[0].FontIndex, Is.EqualTo(1));
        }

        private static int GetRenderedVertexCount(TexpixText text)
        {
            Canvas.ForceUpdateCanvases();
            return text.canvasRenderer.GetMesh().vertexCount;
        }

        private static TexpixAtlas CreateAtlas(out Vector2Int first, out Vector2Int second)
        {
            var atlas = new TexpixAtlas(4, 2, 8, 2, 2);
            Assert.That(atlas.TryAllocateCell(out _, out first), Is.True);
            Assert.That(atlas.TryAllocateCell(out _, out second), Is.True);
            return atlas;
        }

        private static TexpixQuad[] Merge(TexpixAtlas atlas, List<TexpixQuad> quads,
            TexpixOutlineMode mode)
        {
            var merged = new List<TexpixQuad>();
            TexpixGlyphCoverageMerger.Merge(
                new List<TexpixGlyphAtlasSource> { new(atlas.Texture, atlas.Format) }, quads, mode, merged);
            return merged.ToArray();
        }

        private static void AssertCoverageIsUniqueUnitQuads(ReadOnlySpan<TexpixQuad> quads,
            int expectedPixels)
        {
            var covered = new HashSet<(int, int)>();
            foreach (var quad in quads)
            {
                Assert.That(quad.Width, Is.EqualTo(1));
                Assert.That(quad.Height, Is.EqualTo(1));
                Assert.That(covered.Add((quad.X, quad.Y)), Is.True,
                    $"duplicate coverage at ({quad.X}, {quad.Y})");
            }

            Assert.That(covered.Count, Is.EqualTo(expectedPixels));
        }

        private static bool Covers(ReadOnlySpan<TexpixQuad> quads, int x, int y)
        {
            foreach (var quad in quads)
                if (quad.X == x && quad.Y == y)
                    return true;
            return false;
        }
    }
}

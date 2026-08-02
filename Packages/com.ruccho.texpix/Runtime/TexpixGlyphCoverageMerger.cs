using System;
using System.Collections.Generic;
using Unity.Collections;
using UnityEngine;

namespace Texpix
{
    /// <summary>An atlas texture and the packed format used to decode its font pixels.</summary>
    internal readonly struct TexpixGlyphAtlasSource
    {
        public TexpixGlyphAtlasSource(Texture2D texture, TexpixAtlasFormat format)
        {
            Texture = texture;
            Format = format;
        }

        public Texture2D Texture { get; }
        public TexpixAtlasFormat Format { get; }
    }

    /// <summary>
    ///     Resolves glyph bitmaps into one text-space coverage map. Fill has priority
    ///     over outline, and later fills win when rich-text colors overlap.
    /// </summary>
    internal static class TexpixGlyphCoverageMerger
    {
        private const byte FillPriority = 3;

        private static readonly List<AtlasView> SAtlasViews = new();
        private static readonly Dictionary<long, CoveragePixel> SPixels = new();
        private static readonly List<long> SSortedKeys = new();

        public static void Merge(IReadOnlyList<TexpixGlyphAtlasSource> atlases,
            IReadOnlyList<TexpixQuad> source, TexpixOutlineMode outlineMode, List<TexpixQuad> output)
        {
            if (atlases == null)
                throw new ArgumentNullException(nameof(atlases));
            if (source == null)
                throw new ArgumentNullException(nameof(source));
            if (output == null)
                throw new ArgumentNullException(nameof(output));

            output.Clear();
            SAtlasViews.Clear();
            SPixels.Clear();
            SSortedKeys.Clear();

            for (var i = 0; i < atlases.Count; i++)
                SAtlasViews.Add(new AtlasView(atlases[i]));

            for (var order = 0; order < source.Count; order++)
            {
                var quad = source[order];
                if (quad.FontIndex < 0 || quad.FontIndex >= SAtlasViews.Count)
                    continue;

                var atlas = SAtlasViews[quad.FontIndex];
                if (!atlas.IsReadable)
                    continue;

                for (var y = 0; y < quad.Height; y++)
                for (var x = 0; x < quad.Width; x++)
                {
                    var atlasX = quad.AtlasX + x;
                    var atlasY = quad.AtlasY + y;
                    var priority = Classify(atlas.GetLevel(atlasX, atlasY), atlas.Format, outlineMode);
                    if (priority == 0)
                        continue;

                    var key = CoordinateKey(quad.X + x, quad.Y + y);
                    var candidate = new CoveragePixel(priority, atlasX, atlasY, quad.Color, quad.FontIndex);
                    if (!SPixels.TryGetValue(key, out var current) || CandidateWins(candidate, current))
                        SPixels[key] = candidate;
                }
            }

            foreach (var key in SPixels.Keys)
                SSortedKeys.Add(key);
            SSortedKeys.Sort(CompareCoordinates);

            foreach (var key in SSortedKeys)
            {
                var pixel = SPixels[key];
                output.Add(new TexpixQuad
                {
                    X = CoordinateX(key),
                    Y = CoordinateY(key),
                    Width = 1,
                    Height = 1,
                    AtlasX = pixel.AtlasX,
                    AtlasY = pixel.AtlasY,
                    Color = pixel.Color,
                    FontIndex = pixel.FontIndex
                });
            }
        }

        private static bool CandidateWins(in CoveragePixel candidate, in CoveragePixel current)
        {
            return candidate.Priority >= current.Priority;
        }

        private static byte Classify(byte rawLevel, TexpixAtlasFormat format, TexpixOutlineMode outlineMode)
        {
            if (rawLevel == 0)
                return 0;
            if (format == TexpixAtlasFormat.FillOnly || rawLevel >= 3)
                return FillPriority;
            if (outlineMode == TexpixOutlineMode.EightNeighbor)
                return rawLevel;
            if (outlineMode == TexpixOutlineMode.FourNeighbor && rawLevel >= 2)
                return rawLevel;
            return 0;
        }

        private static long CoordinateKey(int x, int y)
        {
            return ((long)y << 32) | (uint)x;
        }

        private static int CoordinateX(long key)
        {
            return (int)key;
        }

        private static int CoordinateY(long key)
        {
            return (int)(key >> 32);
        }

        private static int CompareCoordinates(long left, long right)
        {
            var y = CoordinateY(left).CompareTo(CoordinateY(right));
            return y != 0 ? y : CoordinateX(left).CompareTo(CoordinateX(right));
        }

        private readonly struct CoveragePixel
        {
            public CoveragePixel(byte priority, int atlasX, int atlasY, Color32 color, int fontIndex)
            {
                Priority = priority;
                AtlasX = atlasX;
                AtlasY = atlasY;
                Color = color;
                FontIndex = fontIndex;
            }

            public byte Priority { get; }
            public int AtlasX { get; }
            public int AtlasY { get; }
            public Color32 Color { get; }
            public int FontIndex { get; }
        }

        private readonly struct AtlasView
        {
            private readonly NativeArray<byte> _data;
            private readonly int _rowStride;
            private readonly int _height;
            private readonly int _bitsPerPixel;
            private readonly int _pixelsPerTexel;
            private readonly int _levelMask;

            public AtlasView(in TexpixGlyphAtlasSource source)
            {
                Format = source.Format;
                if (source.Texture == null || !source.Texture.isReadable)
                {
                    _data = default;
                    _rowStride = 0;
                    _height = 0;
                    _bitsPerPixel = 0;
                    _pixelsPerTexel = 0;
                    _levelMask = 0;
                    return;
                }

                _data = source.Texture.GetPixelData<byte>(0);
                _rowStride = source.Texture.width;
                _height = source.Texture.height;
                _bitsPerPixel = TexpixAtlas.BitsPerPixelOf(source.Format);
                _pixelsPerTexel = TexpixAtlas.PixelsPerTexelOf(source.Format);
                _levelMask = (1 << _bitsPerPixel) - 1;
            }

            public TexpixAtlasFormat Format { get; }
            public bool IsReadable => _data.IsCreated;

            public byte GetLevel(int x, int y)
            {
                if ((uint)y >= (uint)_height || x < 0 || x >= _rowStride * _pixelsPerTexel)
                    return 0;
                var packed = _data[y * _rowStride + x / _pixelsPerTexel];
                var shift = x % _pixelsPerTexel * _bitsPerPixel;
                return (byte)(packed >> shift & _levelMask);
            }
        }
    }
}

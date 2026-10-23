#!/usr/bin/env python3
"""Strict source-pinned chat layout query optimization.

Keep layout writer/height caches unchanged. Converts a repeated O(all messages)
visible-cell query into O(log N + visible) when prepared frames are monotone.
Fallback preserves the original scan for invalid/nonmonotonic sizes.
"""
from pathlib import Path
import sys
if len(sys.argv) != 2:
    raise SystemExit("usage: python3 patch_chat_perf.py /path/to/OpenMinis")
p = Path(sys.argv[1]) / "src/ios/Agent/MessageList/MessageListLayout.swift"
s = p.read_text(encoding="utf-8")
def once(old, new, name):
    global s
    n=s.count(old)
    if n != 1:
        raise RuntimeError(f"NO-GO {name}: source drift ({n} anchors)")
    s=s.replace(old,new,1)
once(
'''    private var itemAttributes: [UICollectionViewLayoutAttributes] = []

    /// Total content height''',
'''    private var itemAttributes: [UICollectionViewLayoutAttributes] = []

    /// Only the prepared frames decide if lower-bound search is safe.
    /// Invalid item heights/spacing fall back to the original linear scan.
    /// Unlike speculative skipping, this never drops overlapping cells.
    private var preparedFramesAreMonotone = true

    /// Total content height''',
"frames state")
once(
'''        itemAttributes.removeAll(keepingCapacity: true)
        itemAttributes.reserveCapacity(itemCount)

        var y: CGFloat = 0''',
'''        itemAttributes.removeAll(keepingCapacity: true)
        itemAttributes.reserveCapacity(itemCount)
        preparedFramesAreMonotone = itemSpacing.isFinite && itemSpacing >= 0

        var y: CGFloat = 0''',
"prepare reset")
once(
'''            attrs.frame = CGRect(x: 0, y: y, width: width, height: h)
            itemAttributes.append(attrs)''',
'''            if !h.isFinite || h < 0 {
                preparedFramesAreMonotone = false
            }
            attrs.frame = CGRect(x: 0, y: y, width: width, height: h)
            itemAttributes.append(attrs)''',
"height validation")
old='''        var result: [UICollectionViewLayoutAttributes] = []
        for attrs in itemAttributes {
            if attrs.frame.maxY < expandedRect.minY { continue }
            if attrs.frame.minY > expandedRect.maxY { break }
            result.append(attrs)
        }

        // [ScrollStall] Sampled'''
new='''        var result: [UICollectionViewLayoutAttributes] = []
        if preparedFramesAreMonotone {
            // prepare() emits non-overlapping, y-sorted frames. The original
            // scan visited every preceding item on each viewport query.
            // Lower-bound seeks the first frame whose maxY reaches viewport.
            var low = 0
            var high = itemAttributes.count
            while low < high {
                let mid = low + (high - low) / 2
                if itemAttributes[mid].frame.maxY < expandedRect.minY {
                    low = mid + 1
                } else {
                    high = mid
                }
            }
            var index = low
            while index < itemAttributes.count {
                let attrs = itemAttributes[index]
                if attrs.frame.minY > expandedRect.maxY { break }
                result.append(attrs)
                index += 1
            }
        } else {
            // Preserve exact historical semantics for malformed geometry;
            // never use a binary search on unordered positions.
            for attrs in itemAttributes {
                if attrs.frame.maxY < expandedRect.minY { continue }
                if attrs.frame.minY > expandedRect.maxY { break }
                result.append(attrs)
            }
        }

        // [ScrollStall] Sampled'''
once(old,new,"visible cells selection")
if s.count("preparedFramesAreMonotone") != 4:
    raise RuntimeError("NO-GO unexpected optimization state references")
p.write_text(s,encoding="utf-8")
print("PASS: message layout lower-bound optimization installed; original scan fallback retained")

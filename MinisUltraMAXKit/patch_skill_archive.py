#!/usr/bin/env python3
"""Bounds and path-safety hardening for OpenMinis SKILL ZIP imports."""
from pathlib import Path
import sys
if len(sys.argv)!=2:
    raise SystemExit("usage: patch_skill_archive.py /path/to/OpenMinis")
p=Path(sys.argv[1])/"src/ios/Agent/Session/SkillStore.swift"
s=p.read_text(encoding="utf-8")
def once(a,b,label):
    global s
    count=s.count(a)
    if count!=1:
        raise RuntimeError(f"NO-GO {label}: expected 1 anchor, got {count}")
    s=s.replace(a,b,1)
once(
'''        let entries = try Self.readZipEntries(data: data)

        guard let skillMDEntry''',
r'''        let entries = try Self.readZipEntries(data: data)
        // Treat archive member names as untrusted paths, not filesystem paths.
        // Check the entire archive BEFORE installing a SKILL.md or any siblings.
        guard !entries.isEmpty && entries.count <= 4096,
              entries.allSatisfy({ entry in
                  let name = entry.name
                  let parts = name.split(separator: "/", omittingEmptySubsequences: false)
                  return !name.isEmpty && !name.hasPrefix("/")
                      && !name.contains("\\") && !name.contains("\0")
                      && !parts.contains(where: { $0 == "." || $0 == ".." })
                      && !parts.dropLast().contains(where: { $0.isEmpty })
              }) else {
            throw SkillError.invalidArchive
        }

        guard let skillMDEntry''',
"validate import paths before write")
once(
'''        let skillDir = skillsDir.appendingPathComponent(skill.id)
        let rootfsDir = rootfsSkillsDir.appendingPathComponent(skill.id)

        for entry in entries''',
'''        // An archive rooted one directory deep must not smuggle members
        // outside that root. Validate before any sibling write.
        guard prefix.isEmpty || entries.allSatisfy({ $0.name.hasPrefix(prefix) }) else {
            throw SkillError.invalidArchive
        }
        let skillDir = skillsDir.appendingPathComponent(skill.id)
        let rootfsDir = rootfsSkillsDir.appendingPathComponent(skill.id)

        for entry in entries''',
"validate root prefix")
once(
'''    static func readZipEntries(data: Data) throws -> [ZipEntry] {
        guard data.count >= 22 else { throw SkillError.invalidArchive }''',
'''    static func readZipEntries(data: Data) throws -> [ZipEntry] {
        // Skills are small text/script packages. Large ZIPs/zip bombs must not
        // force huge main-process allocations before the user can cancel.
        guard data.count >= 22 && data.count <= 64 * 1024 * 1024 else {
            throw SkillError.invalidArchive
        }''',
"compressed size cap")
once(
'''        let cdOffset = Int(readU32(data, at: eocdOffset + 16))

        var entries: [ZipEntry] = []
        var pos = cdOffset''',
'''        let cdOffset = Int(readU32(data, at: eocdOffset + 16))
        guard entryCount > 0 && entryCount <= 4096,
              cdOffset >= 0 && cdOffset <= data.count else {
            throw SkillError.invalidArchive
        }

        var decodedTotal = 0
        var entries: [ZipEntry] = []
        var pos = cdOffset''',
"central directory bounds")
once(
'''            let localOffset = Int(readU32(data, at: pos + 42))

            let nameData''',
'''            let localOffset = Int(readU32(data, at: pos + 42))
            guard nameLen > 0, pos + 46 + nameLen + extraLen + commentLen <= data.count,
                  uncompSize <= 32 * 1024 * 1024,
                  decodedTotal <= 128 * 1024 * 1024 - uncompSize else {
                throw SkillError.invalidArchive
            }
            decodedTotal += uncompSize

            let nameData''',
"member bounds and decompression cap")
p.write_text(s,encoding="utf-8")
print("PASS: Skill ZIP path and size limits installed; no original data touched")

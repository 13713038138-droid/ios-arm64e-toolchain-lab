#!/usr/bin/env python3
"""R5 patch: expose GPT-6.1-Sol in the iOS Codex OAuth catalog safely."""
from pathlib import Path
import sys

def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"NO-GO GPT61 {label}: expected one anchor, found {n}")
    return text.replace(old, new, 1)

def edit(root, rel, fn):
    p = root / rel
    if not p.is_file():
        raise RuntimeError(f"NO-GO GPT61: missing pinned source {rel}")
    old = p.read_text(encoding="utf-8")
    new = fn(old)
    if old == new:
        raise RuntimeError(f"NO-GO GPT61: no change for {rel}")
    p.write_text(new, encoding="utf-8")

def patch_types(s):
    anchor = '''    static let gpt6Sol = LLMModel(
        id: "gpt-6-sol",
        displayName: "GPT-6 Sol",
        provider: "OpenAI",
        supportsReasoning: true
    )
'''
    entry = '''    /// GPT-6.1 Sol is available through Codex OAuth on eligible ChatGPT accounts.
    /// Declare reasoning explicitly because models.dev may not yet know this ID.
    static let gpt61Sol = LLMModel(
        id: "gpt-6.1-sol",
        displayName: "GPT-6.1-Sol",
        provider: "OpenAI",
        supportsReasoning: true
    )

'''
    s = replace_once(s, anchor, entry + anchor, "model definition")
    return replace_once(s, "        .gpt6Astra, .gpt6Sol, .gpt6Luna,",
                        "        .gpt6Astra, .gpt61Sol, .gpt6Sol, .gpt6Luna,",
                        "Codex OAuth model list")

def patch_thinking(s):
    return replace_once(
        s,
        '        ({ $0.hasPrefix("gpt-6-astra") }, .max),',
        '''        // GPT-6.1 Sol supports low through max; the existing .ultra UI level
        // remains client-side and maps to the wire "max" effort.
        ({ $0.hasPrefix("gpt-6.1-sol") }, .max),
        ({ $0.hasPrefix("gpt-6-astra") }, .max),''',
        "thinking-level rule")

def patch_provider(s):
    return replace_once(
        s,
        '    static let codexClientVersion = "0.155.0"',
        '''    // GPT-6.1 Sol is withheld from the Codex model catalog for client versions
    // below 0.159.0 despite its registry minimum; 0.159.1 is the release baseline
    // that includes the model. This value feeds discovery and request headers.
    static let codexClientVersion = "0.159.1"''',
        "Codex client-version gate")

def patch_tests(s):
    s = replace_once(s, '        XCTAssertEqual(LLMModel.gpt6Luna.id, "gpt-6-luna")',
        '        XCTAssertEqual(LLMModel.gpt6Luna.id, "gpt-6-luna")\n'
        '        XCTAssertEqual(LLMModel.gpt61Sol.supportsReasoning, true)\n'
        '        XCTAssertEqual(LLMModel.gpt61Sol.id, "gpt-6.1-sol")', "reasoning entry test")
    s = replace_once(s, '        XCTAssertTrue(ids.contains("gpt-6-luna"))',
        '        XCTAssertTrue(ids.contains("gpt-6-luna"))\n'
        '        XCTAssertTrue(ids.contains("gpt-6.1-sol"))', "OAuth picker test")
    s = replace_once(s, '        XCTAssertEqual(ThinkingLevelCatalog.declaredMaxLevel(for: "gpt-6-sol"), .max)',
        '        XCTAssertEqual(ThinkingLevelCatalog.declaredMaxLevel(for: "gpt-6-sol"), .max)\n'
        '        XCTAssertEqual(ThinkingLevelCatalog.declaredMaxLevel(for: "gpt-6.1-sol"), .max)', "thinking ceiling test")
    s = replace_once(s, '        for m in [LLMModel.gpt6Sol, LLMModel.gpt6Luna] {',
        '        for m in [LLMModel.gpt61Sol, LLMModel.gpt6Sol, LLMModel.gpt6Luna] {', "wire reasoning test")
    s = replace_once(s, '        for id in ["gpt-6-sol", "gpt-6-luna"] {',
        '        for id in ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"] {', "nil-flag regression test")
    old = '''        XCTAssertTrue(atLeast(OpenAIProvider.codexClientVersion, "0.155.0"),
                      "gpt-6-sol / gpt-6-luna need >= 0.155.0, got \\(OpenAIProvider.codexClientVersion)")'''
    new = old + '''\n        XCTAssertTrue(atLeast(OpenAIProvider.codexClientVersion, "0.159.1"),
                      "gpt-6.1-sol needs the 0.159.1 Codex client baseline, got \\(OpenAIProvider.codexClientVersion)")'''
    return replace_once(s, old, new, "client-version regression test")

def verify(root):
    t = (root / "src/ios/Providers/LLMTypes.swift").read_text(encoding="utf-8")
    c = (root / "src/ios/Providers/ThinkingLevelCatalog.swift").read_text(encoding="utf-8")
    p = (root / "src/ios/Providers/OpenAI/OpenAIProvider.swift").read_text(encoding="utf-8")
    x = (root / "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift").read_text(encoding="utf-8")
    checks = [
        t.count('id: "gpt-6.1-sol"') == 1,
        t.count('displayName: "GPT-6.1-Sol"') == 1,
        'static let gpt61Sol = LLMModel(' in t and
            'supportsReasoning: true' in t[t.index('static let gpt61Sol'):t.index('static let gpt6Sol')],
        '.gpt6Astra, .gpt61Sol, .gpt6Sol, .gpt6Luna,' in t,
        '({ $0.hasPrefix("gpt-6.1-sol") }, .max)' in c,
        'static let codexClientVersion = "0.159.1"' in p,
        'XCTAssertTrue(ids.contains("gpt-6.1-sol"))' in x and 'LLMModel.gpt61Sol' in x,
        'atLeast(OpenAIProvider.codexClientVersion, "0.159.1")' in x,
    ]
    if not all(checks):
        raise RuntimeError("NO-GO GPT61: post-patch source verification failed")

def apply(root):
    edit(root, "src/ios/Providers/LLMTypes.swift", patch_types)
    edit(root, "src/ios/Providers/ThinkingLevelCatalog.swift", patch_thinking)
    edit(root, "src/ios/Providers/OpenAI/OpenAIProvider.swift", patch_provider)
    edit(root, "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift", patch_tests)
    verify(root)

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python3 patch_gpt61_catalog.py /path/to/OpenMinis", file=sys.stderr)
        return 2
    apply(Path(argv[0]).resolve())
    print("PASS GPT61: model ID, Codex OAuth picker, reasoning rule, 0.159.1 client gate and regression assertions")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

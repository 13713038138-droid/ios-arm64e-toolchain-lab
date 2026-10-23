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
    /// Keep static metadata authoritative when the live catalog omits these fields.
    static let gpt61Sol = LLMModel(
        id: "gpt-6.1-sol",
        displayName: "GPT-6.1-Sol",
        provider: "OpenAI",
        contextWindow: 1_050_000,
        maxOutputTokens: 128_000,
        supportsReasoning: true,
        reasoningEffortValues: ["low", "medium", "high", "xhigh", "max"]
    )

'''
    s = replace_once(s, anchor, entry + anchor, "model definition")
    s = replace_once(
        s,
        '''    static let allOpenAI: [LLMModel] = [
        .gpt54, .gpt52, .gpt5, .gpt41,
        .gpt4o, .gpt4oMini,
        .o3, .o4Mini,
        .codexMini,
    ]''',
        '''    static let allOpenAI: [LLMModel] = [
        .gpt61Sol,
        .gpt54, .gpt52, .gpt5, .gpt41,
        .gpt4o, .gpt4oMini,
        .o3, .o4Mini,
        .codexMini,
    ]''',
        "OpenAI API-key fallback model list",
    )
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
    s = replace_once(
        s,
        '    static let codexClientVersion = "0.155.0"',
        '''    // GPT-6.1 Sol is withheld from the Codex model catalog for client versions
    // below 0.159.0 despite its registry minimum; 0.159.1 is the release baseline
    // that includes the model. This value feeds discovery and request headers.
    static let codexClientVersion = "0.159.1"''',
        "Codex client-version gate")
    return replace_once(
        s,
        '''    var usesChatCompletionsAPI: Bool {
        if forceResponsesAPI { return false }
        if !isOAuth { return true }''',
        '''    var usesChatCompletionsAPI: Bool {
        if forceResponsesAPI { return false }
        // Keep this ID on a live request-routing path so the shipped binary
        // proves the GPT-6.1 patch was linked, not merely present in source.
        // Official OpenAI API-key requests use Responses; custom/Azure endpoints
        // retain their existing routing.
        if model.id.lowercased() == "gpt-6.1-sol",
           customBaseURL == nil, !isAzure {
            return false
        }
        if !isOAuth { return true }''',
        "GPT-6.1 Sol official Responses API routing")


def patch_agent(s):
    anchor = '''        guard !level.isEnabled else { return nil }
        if provider.customBaseURL == nil && !provider.isAzure { return "none" }
        let base = provider.customBaseURL?.lowercased() ?? ""
        let lid = model.id.lowercased()'''
    replacement = '''        guard !level.isEnabled else { return nil }
        let base = provider.customBaseURL?.lowercased() ?? ""
        let lid = model.id.lowercased()
        // GPT-6.1 Sol rejects "none"/"minimal"; OFF uses its lowest valid tier.
        if lid == "gpt-6.1-sol" { return "low" }
        if provider.customBaseURL == nil && !provider.isAzure { return "none" }'''
    return replace_once(s, anchor, replacement, "GPT-6.1 Sol thinking OFF clamp")


def patch_models_api(s):
    anchor = '''            if let reasoning = (item["supports_reasoning"] as? Bool)
                ?? (item["reasoning"] as? Bool) {
                model.supportsReasoning = reasoning
            }
            return model
'''
    replacement = '''            if let reasoning = (item["supports_reasoning"] as? Bool)
                ?? (item["reasoning"] as? Bool) {
                model.supportsReasoning = reasoning
            }
            // GPT-6.1 Sol can be present in the authoritative Codex list while
            // older response shapes omit the reasoning flag. Fill only nil;
            // never override an explicit backend false.
            if id == "gpt-6.1-sol", model.supportsReasoning == nil {
                model.supportsReasoning = true
            }
            return model
'''
    s = replace_once(s, anchor, replacement, "Codex dynamic reasoning fallback")
    call_anchor = "                let models = appendBuiltInImageModels(to: discovered)"
    call_replacement = "                let withGPT61 = appendKnownGPT61SolIfFamilyAvailable(to: discovered)\n                let models = appendBuiltInImageModels(to: withGPT61)"
    s = replace_once(s, call_anchor, call_replacement, "dynamic catalog GPT-6.1-Sol inclusion")
    helper_anchor = "    /// [T-codex-image-models-survive-discovery] Add the built-in Codex image"
    helper = '''    /// Keep the known GPT-6.1-Sol entry available when this account's authoritative
    /// Codex catalog exposes another GPT-6 family model but omits the new sibling.
    /// Do not inject it into unrelated providers or accounts with no GPT-6 access.
    static func appendKnownGPT61SolIfFamilyAvailable(to discovered: [LLMModel]) -> [LLMModel] {
        let ids = Set(discovered.map(\\.id))
        guard !ids.contains(LLMModel.gpt61Sol.id) else { return discovered }
        guard ids.contains("gpt-6-astra") || ids.contains("gpt-6-sol") || ids.contains("gpt-6-luna") else {
            return discovered
        }
        return discovered + [LLMModel.gpt61Sol]
    }

'''
    s = replace_once(s, helper_anchor, helper + helper_anchor, "GPT-6.1-Sol dynamic catalog helper")
    merge_anchor = '''        let byId = Dictionary(enriched.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return fresh.map { authoritative in
            guard var merged = byId[authoritative.id] else { return authoritative }
            if authoritative.contextWindow != nil { merged.contextWindow = authoritative.contextWindow }
            if authoritative.maxOutputTokens != nil { merged.maxOutputTokens = authoritative.maxOutputTokens }
            if authoritative.supportsReasoning != nil { merged.supportsReasoning = authoritative.supportsReasoning }
            if authoritative.modalityOverride != nil { merged.modalityOverride = authoritative.modalityOverride }'''
    merge_replacement = '''        let byId = Dictionary(enriched.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let builtInById = Dictionary(LLMModel.allOpenAICodexOAuth.map { ($0.id, $0) },
                                     uniquingKeysWith: { a, _ in a })
        return fresh.map { authoritative in
            // Preserve live-only models when models.dev has no matching record.
            var merged = byId[authoritative.id] ?? authoritative
            if let builtIn = builtInById[authoritative.id] {
                if merged.contextWindow == nil { merged.contextWindow = builtIn.contextWindow }
                if merged.maxOutputTokens == nil { merged.maxOutputTokens = builtIn.maxOutputTokens }
                if merged.supportsReasoning == nil { merged.supportsReasoning = builtIn.supportsReasoning }
                if merged.reasoningEffortValues == nil { merged.reasoningEffortValues = builtIn.reasoningEffortValues }
                if merged.declaresNoEffortTiers == nil { merged.declaresNoEffortTiers = builtIn.declaresNoEffortTiers }
                if merged.modalityOverride == nil { merged.modalityOverride = builtIn.modalityOverride }
            }
            if authoritative.contextWindow != nil { merged.contextWindow = authoritative.contextWindow }
            if authoritative.maxOutputTokens != nil { merged.maxOutputTokens = authoritative.maxOutputTokens }
            if authoritative.supportsReasoning != nil { merged.supportsReasoning = authoritative.supportsReasoning }
            if authoritative.modalityOverride != nil { merged.modalityOverride = authoritative.modalityOverride }
            if authoritative.reasoningEffortValues != nil { merged.reasoningEffortValues = authoritative.reasoningEffortValues }
            if authoritative.declaresNoEffortTiers != nil { merged.declaresNoEffortTiers = authoritative.declaresNoEffortTiers }
            // Prefer the pinned GPT-6.1 Sol definition over stale models.dev
            // values whenever the live endpoint omits a field.
            if authoritative.id == "gpt-6.1-sol" {
                let sol = LLMModel.gpt61Sol
                if authoritative.contextWindow == nil { merged.contextWindow = sol.contextWindow }
                if authoritative.maxOutputTokens == nil { merged.maxOutputTokens = sol.maxOutputTokens }
                if authoritative.supportsReasoning == nil { merged.supportsReasoning = sol.supportsReasoning }
                if authoritative.reasoningEffortValues == nil { merged.reasoningEffortValues = sol.reasoningEffortValues }
                if authoritative.declaresNoEffortTiers == nil { merged.declaresNoEffortTiers = sol.declaresNoEffortTiers }
            }'''
    return replace_once(s, merge_anchor, merge_replacement, "GPT-6.1 model metadata fallback")

def patch_tests(s):

    dynamic_test = '''    func testCodexDiscoveryGPT61DeclaresReasoningWhenBackendOmitsFlag() {
        let data = Data(#"[{"id":"gpt-6.1-sol","display_name":"GPT-6.1-Sol"}]"#.utf8)
        let models = OpenAIModelsAPI.parseCodexModels(data)
        XCTAssertEqual(models.count, 1)
        guard let model = models.first else {
            XCTFail("Expected one model from the Codex discovery fixture")
            return
        }
        XCTAssertEqual(model.supportsReasoning, true)
        XCTAssertEqual(OpenAIAgentProvider.reasoningEffort(for: model, level: .low), "low")
        XCTAssertEqual(OpenAIAgentProvider.reasoningEffort(for: model, level: .medium), "medium")
    }

    func testGPT61SolHasPinnedMetadataAndEffortLadder() {
        let model = LLMModel.gpt61Sol
        XCTAssertEqual(model.contextWindow, 1_050_000)
        XCTAssertEqual(model.maxOutputTokens, 128_000)
        XCTAssertEqual(model.reasoningEffortValues ?? [], ["low", "medium", "high", "xhigh", "max"])
        XCTAssertEqual(OpenAIAgentProvider.reasoningEffort(for: model, level: .max), "max")
        XCTAssertEqual(OpenAIAgentProvider.reasoningEffort(for: model, level: .ultra), "max")
    }

    func testGPT61SolUsesResponsesAPIForOfficialOpenAIEndpoint() {
        let provider = OpenAIProvider(apiKey: "test", model: .gpt61Sol)
        XCTAssertFalse(provider.usesChatCompletionsAPI)
    }

    func testGPT61SolPreservesCustomEndpointRouting() {
        let provider = OpenAIProvider(apiKey: "test", model: .gpt61Sol,
                                      customBaseURL: "https://example.invalid")
        XCTAssertTrue(provider.usesChatCompletionsAPI)
    }

    func testGPT61SolIsAppendedWhenCodexCatalogHasGPT6Family() {
        let result = OpenAIModelsAPI.appendKnownGPT61SolIfFamilyAvailable(to: [LLMModel.gpt6Sol])
        XCTAssertEqual(result.filter { $0.id == "gpt-6.1-sol" }.count, 1)
        XCTAssertEqual(result.last?.displayName, "GPT-6.1-Sol")
        XCTAssertEqual(result.last?.supportsReasoning, true)
    }

    func testGPT61SolIsNotAppendedToUnrelatedCodexCatalog() {
        let result = OpenAIModelsAPI.appendKnownGPT61SolIfFamilyAvailable(to: [LLMModel.gpt55])
        XCTAssertFalse(result.contains { $0.id == "gpt-6.1-sol" })
    }

'''
    s = replace_once(s, "    func testBothAreOfferedOverCodexOAuth() {",
                    dynamic_test + "    func testBothAreOfferedOverCodexOAuth() {",
                    "dynamic Codex model reasoning test")
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
    agent = (root / "src/ios/Providers/OpenAI/OpenAIAgentProvider.swift").read_text(encoding="utf-8")
    x = (root / "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift").read_text(encoding="utf-8")
    api = (root / "src/ios/Providers/OpenAI/OpenAIModelsAPI.swift").read_text(encoding="utf-8")
    all_openai_start = t.index('static let allOpenAI: [LLMModel] = [')
    all_codex_start = t.index('static let allOpenAICodexOAuth: [LLMModel] = [')
    checks = [
        t.count('id: "gpt-6.1-sol"') == 1,
        t.count('displayName: "GPT-6.1-Sol"') == 1,
        'static let gpt61Sol = LLMModel(' in t and
            'supportsReasoning: true' in t[t.index('static let gpt61Sol'):t.index('static let gpt6Sol')],
        'contextWindow: 1_050_000' in t and 'maxOutputTokens: 128_000' in t,
        'reasoningEffortValues: ["low", "medium", "high", "xhigh", "max"]' in t,
        '.gpt61Sol' in t[all_openai_start:all_codex_start],
        '.gpt6Astra, .gpt61Sol, .gpt6Sol, .gpt6Luna,' in t,
        '({ $0.hasPrefix("gpt-6.1-sol") }, .max)' in c,
        'static let codexClientVersion = "0.159.1"' in p,
        'model.id.lowercased() == "gpt-6.1-sol"' in p and 'customBaseURL == nil, !isAzure' in p,
        'if lid == "gpt-6.1-sol" { return "low" }' in agent,
        'XCTAssertTrue(ids.contains("gpt-6.1-sol"))' in x and 'LLMModel.gpt61Sol' in x,
        'atLeast(OpenAIProvider.codexClientVersion, "0.159.1")' in x,
        'if id == "gpt-6.1-sol", model.supportsReasoning == nil' in api,
        'model.supportsReasoning = true' in api,
        'appendKnownGPT61SolIfFamilyAvailable(to: discovered)' in api,
        'return discovered + [LLMModel.gpt61Sol]' in api,
        'let builtInById = Dictionary(LLMModel.allOpenAICodexOAuth.map' in api,
        'if authoritative.id == "gpt-6.1-sol"' in api,
        'if authoritative.reasoningEffortValues != nil' in api,
        'OpenAIModelsAPI.parseCodexModels(data)' in x and 'reasoningEffort(for: model, level: .medium), "medium"' in x,
        'appendKnownGPT61SolIfFamilyAvailable(to: [LLMModel.gpt6Sol])' in x,
        'testGPT61SolUsesResponsesAPIForOfficialOpenAIEndpoint' in x,
        'testGPT61SolPreservesCustomEndpointRouting' in x,
    ]
    if not all(checks):
        raise RuntimeError("NO-GO GPT61: post-patch source verification failed")

def apply(root):
    edit(root, "src/ios/Providers/LLMTypes.swift", patch_types)
    edit(root, "src/ios/Providers/ThinkingLevelCatalog.swift", patch_thinking)
    edit(root, "src/ios/Providers/OpenAI/OpenAIProvider.swift", patch_provider)
    edit(root, "src/ios/Providers/OpenAI/OpenAIAgentProvider.swift", patch_agent)
    edit(root, "src/ios/Providers/OpenAI/OpenAIModelsAPI.swift", patch_models_api)
    edit(root, "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift", patch_tests)
    verify(root)

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python3 patch_gpt61_catalog.py /path/to/OpenMinis", file=sys.stderr)
        return 2
    apply(Path(argv[0]).resolve())
    print("PASS GPT61: retained model ID, Responses routing, OFF-to-low clamp, 1.05M/128K metadata, effort ladder, live catalog fallback and regression assertions")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

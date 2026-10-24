import tempfile
import unittest
from pathlib import Path
import patch_gpt61_catalog as patch

LLM = '''    static let gpt6Sol = LLMModel(
        id: "gpt-6-sol",
        displayName: "GPT-6 Sol",
        provider: "OpenAI",
        supportsReasoning: true
    )
    static let allOpenAI: [LLMModel] = [
        .gpt54, .gpt52, .gpt5, .gpt41,
        .gpt4o, .gpt4oMini,
        .o3, .o4Mini,
        .codexMini,
    ]
    static let allOpenAICodexOAuth: [LLMModel] = [
        .gpt6Astra, .gpt6Sol, .gpt6Luna,
    ]
'''
THINKING = '''    private static let rules: [(match: (String) -> Bool, max: ThinkingLevel)] = [
        ({ $0.hasPrefix("gpt-6-astra") }, .max),
    ]
'''
PROVIDER = '''    static let codexClientVersion = "0.155.0"
    var usesChatCompletionsAPI: Bool {
        if forceResponsesAPI { return false }
        if !isOAuth { return true }
    }
        // Try to extract error message from JSON body
'''
AGENT = '''        guard !level.isEnabled else { return nil }
        if provider.customBaseURL == nil && !provider.isAzure { return "none" }
        let base = provider.customBaseURL?.lowercased() ?? ""
        let lid = model.id.lowercased()
'''
API = '''            if let reasoning = (item["supports_reasoning"] as? Bool)
                ?? (item["reasoning"] as? Bool) {
                model.supportsReasoning = reasoning
            }
            return model
                let models = appendBuiltInImageModels(to: discovered)
    /// [T-codex-image-models-survive-discovery] Add the built-in Codex image
        let byId = Dictionary(enriched.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return fresh.map { authoritative in
            guard var merged = byId[authoritative.id] else { return authoritative }
            if authoritative.contextWindow != nil { merged.contextWindow = authoritative.contextWindow }
            if authoritative.maxOutputTokens != nil { merged.maxOutputTokens = authoritative.maxOutputTokens }
            if authoritative.supportsReasoning != nil { merged.supportsReasoning = authoritative.supportsReasoning }
            if authoritative.modalityOverride != nil { merged.modalityOverride = authoritative.modalityOverride }
'''
TESTS = '''    func testBothAreOfferedOverCodexOAuth() {
        XCTAssertEqual(LLMModel.gpt6Luna.id, "gpt-6-luna")
        XCTAssertTrue(ids.contains("gpt-6-luna"))
        XCTAssertEqual(ThinkingLevelCatalog.declaredMaxLevel(for: "gpt-6-sol"), .max)
        for m in [LLMModel.gpt6Sol, LLMModel.gpt6Luna] {
        for id in ["gpt-6-sol", "gpt-6-luna"] {
        XCTAssertTrue(atLeast(OpenAIProvider.codexClientVersion, "0.155.0"),
                      "gpt-6-sol / gpt-6-luna need >= 0.155.0, got \\(OpenAIProvider.codexClientVersion)")
'''

class Tests(unittest.TestCase):
    def tree(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        data = {
            "src/ios/Providers/LLMTypes.swift": LLM,
            "src/ios/Providers/ThinkingLevelCatalog.swift": THINKING,
            "src/ios/Providers/OpenAI/OpenAIProvider.swift": PROVIDER,
            "src/ios/Providers/OpenAI/OpenAIAgentProvider.swift": AGENT,
            "src/ios/Providers/OpenAI/OpenAIModelsAPI.swift": API,
            "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift": TESTS,
        }
        for rel, content in data.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return root

    def test_applies_catalog_and_version_gate(self):
        root = self.tree()
        patch.apply(root)
        patch.verify(root)
        types = (root / "src/ios/Providers/LLMTypes.swift").read_text()
        self.assertIn('id: "gpt-6.1-sol"', types)
        codex_start = types.index("static let allOpenAICodexOAuth: [LLMModel] =")
        codex_body = types[codex_start:types.index("\n    ]", codex_start)]
        self.assertNotIn(".gpt61Sol", codex_body, "unsupported Codex accounts must not receive a static model seed")
        self.assertIn('XCTAssertFalse(ids.contains("gpt-6.1-sol")', (root / "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift").read_text())
        self.assertIn("contextWindow: 1_050_000", types)
        self.assertIn("maxOutputTokens: 128_000", types)
        self.assertIn('reasoningEffortValues: ["low", "medium", "high", "xhigh", "max"]', types)
        self.assertIn(".gpt61Sol", types[types.index("static let allOpenAI: [LLMModel] ="):types.index("static let allOpenAICodexOAuth: [LLMModel] =")])
        provider = (root / "src/ios/Providers/OpenAI/OpenAIProvider.swift").read_text()
        self.assertIn('static let codexClientVersion = "0.159.1"', provider)
        self.assertIn('detail.localizedCaseInsensitiveContains("not supported when using Codex")', provider)
        self.assertIn('model.id.lowercased() == "gpt-6.1-sol"', provider)
        self.assertIn("customBaseURL == nil, !isAzure", provider)
        agent = (root / "src/ios/Providers/OpenAI/OpenAIAgentProvider.swift").read_text()
        self.assertIn('if lid == "gpt-6.1-sol" { return "low" }', agent)
        api = (root / "src/ios/Providers/OpenAI/OpenAIModelsAPI.swift").read_text()
        self.assertIn('if id == "gpt-6.1-sol", model.supportsReasoning == nil', api)
        self.assertIn("model.supportsReasoning = true", api)
        self.assertNotIn("appendKnownGPT61SolIfFamilyAvailable", api)
        self.assertIn("let models = appendBuiltInImageModels(to: discovered)", api)
        self.assertIn("var merged = byId[authoritative.id] ?? authoritative", api)
        self.assertIn('if authoritative.id == "gpt-6.1-sol"', api)
        self.assertIn("if authoritative.reasoningEffortValues != nil", api)
        swift_tests = (root / "src/ios/MinisTests/GPT6SolLunaOpus55Tests.swift").read_text()
        self.assertIn("guard let model = models.first else", swift_tests)
        self.assertIn("testGPT61SolThinkingOffFallsBackToLow", swift_tests)
        self.assertIn("testGPT61SolUsesResponsesAPIForOfficialOpenAIEndpoint", swift_tests)
        self.assertIn("testGPT61SolPreservesCustomEndpointRouting", swift_tests)

    def test_fails_closed_on_source_drift(self):
        root = self.tree()
        p = root / "src/ios/Providers/LLMTypes.swift"
        p.write_text(LLM.replace('id: "gpt-6-sol"', 'id: "renamed-model"'), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "model definition"):
            patch.apply(root)

    def test_repeated_application_fails_closed(self):
        root = self.tree()
        patch.apply(root)
        with self.assertRaises(RuntimeError):
            patch.apply(root)

if __name__ == "__main__":
    unittest.main()

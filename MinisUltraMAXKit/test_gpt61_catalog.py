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
    static let allOpenAICodexOAuth: [LLMModel] = [
        .gpt6Astra, .gpt6Sol, .gpt6Luna,
    ]
'''
THINKING = '''    private static let rules: [(match: (String) -> Bool, max: ThinkingLevel)] = [
        ({ $0.hasPrefix("gpt-6-astra") }, .max),
    ]
'''
PROVIDER = '''    static let codexClientVersion = "0.155.0"
'''
TESTS = '''        XCTAssertEqual(LLMModel.gpt6Luna.id, "gpt-6-luna")
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
        self.assertIn('id: "gpt-6.1-sol"', (root / "src/ios/Providers/LLMTypes.swift").read_text())
        self.assertIn('static let codexClientVersion = "0.159.1"', (root / "src/ios/Providers/OpenAI/OpenAIProvider.swift").read_text())

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

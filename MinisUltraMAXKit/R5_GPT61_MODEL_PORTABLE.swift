#!/usr/bin/env swift
// R5.3 executable macOS Swift source-contract checks for the pinned OpenMinis tree.
// The iOS simulator cannot link the device-only libish_emu.a. This test is
// intentionally labeled STANDALONE, never an app/XCTest or account validation.
import Foundation

guard CommandLine.arguments.count == 2 else {
    fputs("usage: swift R5_GPT61_MODEL_PORTABLE.swift /path/to/OpenMinis\n", stderr)
    exit(2)
}
let base = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
func source(_ relative: String) -> String {
    let path = base.appendingPathComponent("src/ios/" + relative)
    return (try? String(contentsOf: path, encoding: .utf8)) ?? ""
}
func block(_ text: String, after anchor: String, before suffix: String = "\n    ]") -> String {
    guard let range = text.range(of: anchor) else { return "" }
    let remaining = text[range.lowerBound...]
    guard let end = remaining.range(of: suffix) else { return "" }
    return String(remaining[..<end.upperBound])
}
var failures = 0
func check(_ desc: String, _ ok: Bool) {
    print("\(ok ? "PASS" : "FAIL"): \(desc)")
    if !ok { failures += 1 }
}
let llm = source("Providers/LLMTypes.swift")
let codex = source("Providers/OpenAI/OpenAIModelsAPI.swift")
let provider = source("Providers/OpenAI/OpenAIProvider.swift")
let agent = source("Providers/OpenAI/OpenAIAgentProvider.swift")
let thinking = source("Providers/ThinkingLevelCatalog.swift")
let sourceTests = source("MinisTests/GPT6SolLunaOpus55Tests.swift")
check("shipping source tree readable",
      [llm, codex, provider, agent, thinking, sourceTests].allSatisfy { !$0.isEmpty })
let definition = block(llm, after: "static let gpt61Sol = LLMModel(", before: "\n    )")
check("GPT-6.1 Sol exact ID and metadata",
      definition.contains("gpt-6.1-sol") && definition.contains("1_050_000") &&
      definition.contains("128_000") && definition.contains("reasoningEffortValues"))
let apiList = block(llm, after: "static let allOpenAI: [LLMModel] = [")
let codexList = block(llm, after: "static let allOpenAICodexOAuth: [LLMModel] = [")
check("API-key built-in catalog may offer the Sol model",
      apiList.contains(".gpt61Sol"))
check("Codex OAuth static fallback MUST NOT claim Sol entitlement",
      !codexList.contains(".gpt61Sol") && codexList.contains(".gpt6Sol"))
check("Live Codex dynamic model ID is honored without hardcoded insertion",
      codex.contains("fetchCodexBackendModels(token: token, accountId: accountId)") &&
      codex.contains("if authoritative.id == \"gpt-6.1-sol\"") &&
      !codex.contains("appendKnownGPT61SolIfFamilyAvailable"))
check("Unsupported-model Codex error is identified by either JSON error shape",
      provider.contains("not supported when using Codex") &&
      provider.contains("json[\"detail\"]") &&
      provider.contains("json[\"error\"]"))
check("Official API path uses Responses for this model",
      provider.contains("model.id.lowercased() == \"gpt-6.1-sol\"") &&
      provider.contains("customBaseURL == nil, !isAzure"))
check("Thinking OFF maps only this ID to low",
      agent.contains("if lid == \"gpt-6.1-sol\" { return \"low\" }") &&
      thinking.contains("hasPrefix(\"gpt-6.1-sol\")"))
check("iOS XCTest source covers dynamic discovery and excludes unauthorized static seed",
      sourceTests.contains("testCodexDiscoveryGPT61DeclaresReasoningWhenBackendOmitsFlag") &&
      sourceTests.contains("XCTAssertFalse(ids.contains(\"gpt-6.1-sol\")"))
print(failures == 0 ? "STANDALONE SWIFT CONTRACTS: PASS" : "STANDALONE SWIFT CONTRACTS: NO-GO \(failures)")
exit(failures == 0 ? 0 : 1)

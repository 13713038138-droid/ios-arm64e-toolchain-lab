# Minis Dev Ultra MAX R5.3 — Model 400 + nonexpert developer continuation

## The observed case and correct limit
On the last installable R5, GPT-6.1 Sol was not in the default model picker.
An official Minis backup restored a model entry, after which it became visible,
but a real request returned HTTP 400. The device screenshot shows:
  Provider error: [400] The 'gpt-6.1-sol' model is not supported when using Co...
This agrees with the pinned OpenMinis Codex error format for a ChatGPT account
model rejection. Visibility is not authorization; we now have concrete evidence
of this account/session's route being denied, not only a bare 400 status. Do not label a restored model
as working, and never invent an alias, spoof account entitlement or suppress
the error.

The pinned OpenMinis BackupImporter merges data/provider_config.json
instances/modelEntries/modelGroups by id. New OAuth provider setup seeds its
compiled static model list and later refreshes the server catalog.
A restored item can therefore be present even if the online account catalog
does not expose it. Model-route/client-version, effort and account limitations
are independent checks.

R5.2 source patch originally inserted a GPT-6.1 Sol entry into the Codex
OAuth static seed list. Real device evidence showed this is misleading, so R5.3
removes that forced static seed but preserves the GPT-6.1 API-key catalog entry,
Responses routing, effort metadata and enrichment ONLY if authenticated Codex
model discovery itself returns the id. Client version 0.159.1 is not a
substitute for server account authorization. R5.3 additionally
recognizes the precise server-rejection phrase "not supported when using Codex"
in response detail and reports an account-model denial rather than a generic
400. This diagnostic patch does NOT unlock the model.

### Reproduction acceptance
1. Test clean R5 upgrade with a signed-in Codex account: record model IDs from
   live /backend-api/codex/models for that account (never record the token).
2. Test model picker before/after optional backup import, compare stable model IDs
   and provider instance IDs. Imported records are not official server authority.
3. On HTTP 400, preserve redacted response detail/error.message and requested
   endpoint/model ID/effort only. Categorize: account-denied; invalid model ID;
   invalid effort; request-schema/endpoint mismatch; or insufficient details.
4. Reproduce with one minimal authorized request. If server denies model entitlement,
   stop retries and offer an actual available model. If request format is rejected,
   fix only the offending field, then test Codex OAuth + API-key + custom provider.
5. Simulator XCTest, Release compile/signature/SHA-256, then real TrollStore
   device request are separate gates. CI without a live account never proves live
   GPT-6.1 entitlement.

## What R5.3 ships in its source branch
- /devcontinue: resume latest verified project/context and journal; pick, attempt
  and verify the next safe bounded step; explain failures in plain language.
- /devfix: inspect error and relevant source/log, classify root-cause candidate,
  apply minimal fix with focused tests; avoid guesswork and endless retries.
- minis-dev-ultra assist --error 'HTTP 400' or --log PATH: offline, bounded
  text classifier with one next action. It does not execute or approve repairs.
- minis-dev-continuation: new independently versioned bundled skill that installs
  into existing user data without overwriting an edited minis-dev-ultra skill.
- Model 400 clarity patch in OpenAIProvider.mapHTTPError, narrowly gated on
  actual Codex model-denial text in either detail or error.message.
- Removed forced GPT-6.1 Sol from Codex OAuth static fallbacks, retaining the
  separate OpenAI API-key model definition and dynamic live-discovery behavior.
  Restored entries remain preserved by existing backup/absence-grace policy;
  they are not proof that this account can send successful requests.

## Priority improvement assessment

### Priority 1 — partial in R5.3
- Nonexpert interpretation / "continue and fix" defaults: implemented in
  slash entries, fallback skill and classifier; pending device behavior validation.
- Reliable resume from previous stage: existing taskctl journal; no daemon or
  promise of autonomous execution when Minis is closed. Integration quality must
  be evaluated on real user projects.
- Provider model 400 clarity: screenshot confirms a current Codex account-model
  denial; no additional secret, account data or repeat request is necessary to
  establish this particular cause. Live fix requires an actually authorized
  provider/model, not a user-agent or model-picker patch.

### Priority 2 — not yet fully implemented
- Automatic GitHub Actions failure collection and narrow patch attempts gated
  by repo access, non-destructive file diff, retry budget and human approvals.
- First-error extraction from xcodebuild/swiftc/ldid/codesign logs with
  independent source/missing SDK versus ABI distinction; current classifier is
  advisory rather than an exhaustive diagnostic engine.
- Persistent, searchable project-level acceptance criteria and cross-session
  resumable test matrix, without guessing unmounted files.

### Priority 3 — not shipped
- Full multi-file native IDE, compiler/SDK download manager and daemon-backed
  persistent jobs; existing Theos factory only builds where compatible tools
  and SDKs are genuinely available.
- Automatic post-install device instrumentation, crash symbolication, process
  ownership verification and privileged install service.
- Unrestricted token limits, server-locked model access, omniscient ABI guesses
  or universal unsupported-device compatibility. These must not be claimed.

## Non-destructive release rules
Never overwrite the App Store Minis or stable Stheno, restore credentials
silently, force an IPA install, publish the user's private sources in the public
toolchain repository, or mark a build as installable without signature, SHA-256,
rollback and relevant device checks. The R5.3 branch remains isolated until
its portable, pinned-source and device build gates are independently verified.

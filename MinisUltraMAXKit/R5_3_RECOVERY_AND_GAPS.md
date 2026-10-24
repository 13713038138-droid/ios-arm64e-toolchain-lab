# Minis Dev Ultra MAX R5.3 — Model 400 + nonexpert developer continuation

## The observed case and correct limit
On the last installable R5, GPT-6.1 Sol was not in the default model picker.
An official Minis backup restored a model entry, after which it became visible,
but a real request returned HTTP 400. Visibility is not authorization and HTTP
400 alone does not identify the rejected field. Do not label a restored model
as working, and never invent an alias, spoof account entitlement or suppress
the error.

The pinned OpenMinis BackupImporter merges data/provider_config.json
instances/modelEntries/modelGroups by id. New OAuth provider setup seeds its
compiled static model list and later refreshes the server catalog.
A restored item can therefore be present even if the online account catalog
does not expose it. Model-route/client-version, effort and account limitations
are independent checks.

R5.2 source patch adds the GPT-6.1 Sol catalog entry, the Codex client version
0.159.1, Responses routing and effort metadata, with tests. R5.3 additionally
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
  actual Codex model-denial text.

## Priority improvement assessment

### Priority 1 — partial in R5.3
- Nonexpert interpretation / "continue and fix" defaults: implemented in
  slash entries, fallback skill and classifier; pending device behavior validation.
- Reliable resume from previous stage: existing taskctl journal; no daemon or
  promise of autonomous execution when Minis is closed. Integration quality must
  be evaluated on real user projects.
- Provider model 400 clarity: recognized denial, but needs the user's real
  redacted error text to distinguish account vs payload.

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

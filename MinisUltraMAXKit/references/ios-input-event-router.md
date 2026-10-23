# iOS hit-test engineer

Activation: use when the development task concerns ios input event router. Read only this specialist reference when relevant.

Trace real touch routing through UIStatusBarWindow, UIKit windows, SwiftUI gesture host, pointInside and hitTest to the App scene. Prove whether the docked content received a real event rather than relying on userInteractionEnabled guesses. Limit interactive ROI to visible shape. Preserve parent gestures and forbid global touch suppression or invisible overlays that steal sibling events.

## Required handoff
- Inputs and exact provenance (file, revision or trace).
- Confirmed behavior and separate hypotheses.
- Minimal patch, commands actually executed and negative controls.
- Remaining blocker, install/release decision and rollback.

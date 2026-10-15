# Sheet-metal workflow toolkit

This toolkit adds verified, connector-level workflows for creating and editing ordinary sheet-metal plates and panels in SOLIDWORKS. It is designed for callers that need predictable geometry, explicit dimensional meaning, and native readback after every change.

## Design goals

- Use native SOLIDWORKS sheet-metal features rather than approximating bends with generic solids.
- Require thickness, inside bend radius, and dimensional interpretation on every creation request.
- Keep document creation separate from saving, PDM, overwrite, deletion, and export decisions.
- Inspect existing production parts before editing them.
- Reject stale document state, ambiguous topology, rebuild errors, and parameter readback mismatches.
- Keep flat-pattern suppression, unfold/fold features, and feature-tree rollback as separate operations.

## Profile and template

The built-in profile is named `standard_2026`. It resolves a part template labelled `2026 plaat`.

Set `SW_MCP_SHEETMETAL_TEMPLATE` to an exact `.prtdot` path, or set `SW_MCP_TEMPLATE_DIR` to a directory containing the template. Profile discovery reports whether the template was resolved; creation stops without opening a document when it is unavailable.

The profile records preferred plane and origin conventions, template-controlled bend allowance, relief defaults, and DXF bend-line defaults. Thickness and inside radius remain explicit job inputs.

## Dimensional meaning

Every plate or panel request requires one of:

- `flat_blank`: width and height describe the initial flat rectangular blank.
- `finished_outer`: width and height describe the expected folded outside envelope.

Callers must choose deliberately; the connector never guesses.

## Main workflow tools

| Tool | Purpose |
| --- | --- |
| `list_sheet_metal_profiles` | Report available profiles, template resolution, and defaults. |
| `create_sheet_metal_plate` | Create an unsaved rectangular sheet-metal base flange with explicit dimensions, thickness, radius, and dimension mode. |
| `create_sheet_metal_panel` | Create an unsaved plate and apply declarative side-based flanges, hems, corners, and reliefs. |
| `inspect_sheet_metal_part` | Read document/configuration identity, sheet-metal parameters, feature state, bodies, bounds, rebuild problems, persistent topology references, and an edit token. |
| `inspect_sheet_metal_edit` | Prepare a guarded parameter edit and return the exact token and native feature identity required by the apply call. |
| `verify_sheet_metal_part` | Compare native readback with expected dimensions, thickness, radius, body count, volume sanity, feature state, and rebuild status. |
| `inspect_sketch_alignment` | List compatible straight sketch lines and model edges with direction, gap, relations, and persistent references. |
| `set_sketch_line_collinear_to_edge` | Add a direct native collinear relation using inspected references, restore tree state, rebuild, and verify. |

## Native fabrication operations

The connector exposes guarded operations for base-flange and edge-flange parameter editing, hems, jogs, sketched bends, rips, normal cuts, closed corners, break corners, and corner reliefs. Native unfold/fold supports an explicit fixed face and either selected bends or `all_bends`.

Each apply operation reads the created or edited feature definition back from SOLIDWORKS. A successful COM return value alone is not treated as proof of success.

## Inspect, apply, verify

Existing saved parts follow this sequence:

1. Inspect the active document and intended feature.
2. Keep the returned edit token and persistent feature/topology references.
3. Submit those exact values to the apply tool.
4. Rebuild and verify native feature definitions, bounds, volume sanity, and error state.
5. Save separately only after the caller has reviewed the result.

The token binds document identity, active configuration, feature update stamps, persistent references, feature state, and bounds. Any intervening change makes it stale.

## Panel side declarations

Panel features use semantic sides—`left`, `right`, `bottom`, and `top`—instead of asking callers to retain temporary edge indices. The workflow resolves topology again after each geometry-changing feature.

## Rollback and alignment

Sketch alignment moves the rollback bar only as far as required to make the sketch and model edge available. It restores the requested tree state afterward. If SOLIDWORKS rejects the direct collinear relation, the connector stops; it does not silently create converted construction geometry.

## Flat pattern, unfold/fold, and DXF

- Flat-pattern suppression changes the state of the generated flat-pattern feature.
- Unfold/fold creates native manufacturing features around a chosen fixed face.
- Rollback changes which feature-tree history is currently active.
- DXF export is independent: it validates the output entity section and checks for bend-layer entities when bend lines were requested and bends exist.

## Safety boundaries

Creation tools leave new documents unsaved. Editing tools do not save, overwrite, delete, close, or export production documents. PDM naming, metadata prompts, duplicate cleanup, and vault operations are intentionally outside this toolkit.

## Validation

Offline tests cover schemas, invalid dimensions, stale tokens, ambiguous selection, native readback failures, and mocked COM behavior. Live regressions run only in newly created disposable parts and restore the original SOLIDWORKS session afterward.

The live-verified matrix currently includes both dimension modes, base and edge flanges, hems, normal cuts, break corners, sketched bends, selective and all-bend unfold/fold, rollback, sketch-edge collinearity, parameter edits, and DXF validation. Jog, rip, corner-relief, and closed-corner implementations have offline coverage; their dedicated live regression matrix remains follow-up work.

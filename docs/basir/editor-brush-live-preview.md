# Overlapping brush preview regression

The combined testing image `sha-8bbd0b9` introduced a live-preview regression. This is separate from the unresolved original DW-894 wrong-mask hover and DW-895 saved-pixel-loss reports.

## Reproduction and branch isolation

Paint a continuous vertical mask, then hold a second horizontal stroke that enters and leaves the painted area. Sample the already drawn portion of the second stroke while the pointer remains down. The preview disappears when entering the first mask and returns on mouse-up.

The same native Chromium pointer sequence was run against production standalone editor builds at the exact image source commits:

| Source | Commit | Preview during overlap |
|---|---|---|
| Previously tested baseline | `0a8114b94` | Visible |
| DW-894 alone | `b88010372` | Erased on mask entry; restored on release |
| DW-895 alone | `f2375f430` | Visible |
| Combined testing build | `8bbd0b9a3` | Erased on mask entry; restored on release |

A point on the unfinished second stroke changed from red `[255,0,0,255]` to white `[255,255,255,255]` on entry in DW-894/combined, while `annotation.isDrawing` remained true. After release it became the normal translucent red `[255,102,102,255]`. The baseline and DW-895 preserved that point during the held stroke. These are editor source-build comparisons, not deployments of the containers.

## Root cause and fix

DW-894 broadened `HtxBrushView` mouse-over/out highlighting. That changes the parent Konva Group opacity, which schedules a full layer redraw. `BrushRegion.preDraw` paints unfinished points directly onto the scene canvas; the pending points are private `cachedPoints` and do not enter `touches` until `endPath` on mouse-up. The redraw replays the committed scene graph and therefore removes the unfinished preview. On mouse-up, `endPath` commits those points and the complete stroke becomes visible again. The reproduced regression is a rendering defect, not stored pixel loss.

Brush hover now respects the editor's existing `getSkipInteractions` policy (brush/eraser tools disable region interactions), and both mouse entry and exit avoid highlight mutation while the annotation is drawing. Stale hover is cleared after drawing ends or when changing to a tool that suppresses region interactions. This cleanup checks that the temporary drawing region is still alive. Selection/linking-mode hover, cursor behavior, hit testing, and normal Regions-panel actions remain available.

## Regression coverage and limits

`basir_brush_live_preview.cy.ts` uses native held-pointer events and examines actual rendered scene canvas pixels after React/Konva animation frames, before mouse-up. It checks entry and exit for both a fresh stroke-based mask and an RLE mask reopened for editing, on pages with different dimensions. The test then uses the real editor Submit/Update event, verifies painted pixel samples in its RLE payload, reinitializes from that JSON payload, and compares every decoded RGBA byte after reopening. It does not substitute serialization for the live-preview check. Both live-preview cases fail against the unfixed DW-894 build.

The standalone browser test covers editor submission callbacks and JSON reopening; backend mask-coverage tests separately cover actual POST/PATCH/PUT/GET transport and stored pixel coverage, including author/audit and webhook rollback regressions. No production annotations are edited or repaired.

DW-892 page grouping and DW-896 visibility remain in the combined testing branch. User testing approved those two features. The original intermittent DW-894 and DW-895 issues remain unresolved and their PRs remain drafts; fixing this regression is not evidence that those separate reports are resolved.

## Subsequent opacity correction

The mechanism above describes the implementation at sha-8bbd0b9. A later baseline comparison found that direct pending-stroke drawing also bypassed mask opacity, already in sha-0a8114b. Pending strokes now participate in the normal per-mask scene compositor and survive redraws before mouse-up. The hover guards from this preview fix remain in place. See [editor-brush-opacity.md](editor-brush-opacity.md) for the separate color investigation and tests.

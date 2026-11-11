# Same-mask brush opacity

This investigation concerns the shade of overlapping brush pixels, independently of the unresolved original DW-894 wrong-mask hover and DW-895 saved-pixel-loss reports.

## Reproduction and baseline comparison

Native Chromium pointer sequences were run against production standalone editor builds at the exact source commits for baseline `sha-0a8114b` and the current combined image `sha-8f180b2`. These are source-build comparisons, not deployments of those containers. Both produced the same results on a white image with a red mask at the default 60% opacity:

| Sequence / sample | Pointer held | Released | JSON reopened |
|---|---|---|---|
| One continuous stroke, including self-overlap | `[255,0,0]` | `[255,102,102]` | `[255,102,102]` |
| Restarted stroke within the same mask: old-only pixels | `[255,102,102]` | `[255,102,102]` | `[255,102,102]` |
| Restarted stroke within the same mask: overlap/new pixels | `[255,0,0]` | `[255,102,102]` | `[255,102,102]` |
| Two separate masks: overlapping pixels | `[255,0,0]` | `[255,41,41]` | `[255,41,41]` |

Samples were taken inside broad strokes, away from antialiased edges and the pointer. Highlight state remained false. Same-mask restart retained one region; separate-mask painting produced two. Every decoded RGBA byte survived JSON reopening in these probes. Thus the reproduced same-mask shade mismatch is a pre-existing live-preview defect, not a regression introduced by the four-task stack, not hover/selection styling, and not opacity accumulating in the committed same-mask raster. The darker committed overlap of two distinct masks is intentional and retained.

## Cause and correction

`BrushRegion.preDraw` painted temporary stroke segments directly onto the shared scene canvas, bypassing the Group opacity used for committed mask rendering. New segments were therefore fully opaque over the translucent committed mask. Simply applying 60% opacity per segment would accumulate opacity on overlap and would also be wrong.

Pending points now remain in the same private, uncommitted cache and are exposed read-only to the scene renderer. `preDraw` requests a Konva `batchDraw`, coalescing pointer events to animation frames. The existing per-mask offscreen compositor combines RLE, completed strokes and the current pending stroke at full alpha; the enclosing mask Group applies opacity once to their union. The offscreen canvas transform is reset before clearing each frame so zoom/pan cannot leave stale pixels. Clipping remains with the existing image Group. Eraser composition stays inside the selected mask's offscreen canvas rather than cutting other regions out of the shared layer.

No pending point is added to persisted `touches` before mouse-up, and the existing endPath/serialization/RLE/API paths are unchanged. Regions remain separate and independently translucent. No historical annotations, authors, access-control rules, webhook validation or rollback handling are altered. The previous hover guards remain in place.

## Browser regression coverage

`basir_brush_opacity.cy.ts` uses native held-pointer events and reads actual rendered canvas colors after animation frames without forcing a redraw. Its three scenarios cover continuous self-overlap, restarting on saved RLE on a different-sized page with zoom/pan, and separate same-label masks. It checks RGB/alpha during painting, after release, after real editor Submit/Update callbacks, and after JSON reopening; it compares every decoded coverage byte and checks painted support. The separate-mask scenario additionally erases the upper mask while held, confirms the lower mask stays visible, and verifies the lower mask's saved bytes are unchanged. All three color scenarios fail on the old baseline's held-pointer checks and pass with the correction.

The existing held-stroke preview regression remains required, as do combined DW-892 page grouping, DW-896 visibility, hover, mask persistence, and backend permission/audit/webhook tests. Browser persistence coverage exercises submission callbacks and JSON reopening; actual API storage/transport is checked separately by backend mask-coverage tests. The original intermittent DW-894/DW-895 reports remain unresolved.

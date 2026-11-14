# Basir editor consolidation status

The reference source for the tested combined image `sha-619a283` is commit `619a283abb5802a9fd6bd8e7a3b980d432a7dba5`. Its runtime changes are covered by PRs #19–#22. The temporary integration branch is a testing reference and must not be merged separately when these PRs are consolidated.

| Task | Validated implementation | Production-report status |
|---|---|---|
| DW-892 / PR #19 | Regions grouped by actual saved image/page association; row navigation and existing actions retained | Passed owner manual testing |
| DW-896 / PR #22 | Ctrl+Alt+H invokes the existing annotation-wide visibility action, including all pages | Passed owner manual testing |
| DW-894 / PR #20 | Page/task hover cleanup and guarded hit-cache/async image handling; live-preview regression fix; uniform per-mask opacity for pending and committed strokes | Original intermittent wrong-mask highlight report remains **unresolved**; its exact production cause is unconfirmed |
| DW-895 / PR #21 | Preserve the current native brush raster during a controlled image-loading serialization transition | Original report of portions of saved continuous masks disappearing remains **unresolved**; its normal production trigger has not been reproduced |

The owner authorized merging the reviewed, validated partial fixes, including the preview and opacity corrections. Readiness or merging of PR #20/#21 is **not** evidence that the original DW-894/DW-895 production reports are resolved. Do not mark those Jira tasks resolved on the basis of this consolidation. DW-893 remains paused and outside this work.

## Scope and limits

The preview regression introduced by earlier DW-894 changes was reproduced and corrected: pending pixels remain visible while the pointer crosses existing paint. The opacity mismatch was independently reproduced in baseline `sha-0a8114b`; it was a pre-existing preview defect. Pending strokes now share the existing per-mask compositor, so opacity applies once within a mask while independent masks retain their intentional overlap. The original reports above are separate from these verified corrections.

The DW-895 partial fix covers a controlled case where an edited mask's fresh raster was replaced by its initial wire snapshot while image display was marked loading. That transition has not been established as the cause of the owner's ordinary multiple-object, no-eraser, usually-no-page-switch report. It does not repair historical annotations. Missing pixels already absent from stored RLE require an intact draft/history/backup to investigate recovery separately.

Browser tests check actual held-stroke colors/coverage, continuous and restarted strokes, separate masks and erasure, different page dimensions, zoom/pan, editor Submit/Update payloads and JSON reopening. Backend tests separately check actual POST/PATCH/PUT/GET stored coverage, original authors and updated_by, access restrictions, and webhook rejection/rollback. Browser JSON reopening is not an end-to-end production storage test.

See [editor-brush-live-preview.md](editor-brush-live-preview.md), [editor-brush-opacity.md](editor-brush-opacity.md), and [editor-DW-895.md](editor-DW-895.md) for reproduction evidence and limits. Consolidation must retain access-control/Keycloak/annotation-editing behavior already merged in PRs #15–#18. No production-data repair, deployment, Jira resolution, or GitLab change is part of consolidation.

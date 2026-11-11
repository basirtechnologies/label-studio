# DW-895 mask persistence investigation

The reported normal sequence (multiple continuous object masks on one page, no erasing or page switch) did not lose decoded pixels in the first Chromium checks. This does not establish the production trigger.

A separate, concrete serialization loss was reproduced: reopen saved RLE, add brush strokes, and serialize while the Image entity's `imageLoaded` flag is false. Controlling that loading flag in the browser produced 1,803 intended painted pixels but only 876 pixels in the submission payload. `Image.createSerializedResult` returned `_rawResult`, its initial wire snapshot, instead of the freshly composed brush raster. This is a pre-API loss; storage or webhooks need not mutate pixels to reproduce it. The loading transition was simulated and has not been confirmed as the production trigger.

The fix retains the current brush RLE when native dimensions and a composed raster are available. Other image-region raw-result fallback behavior remains unchanged. No historical annotation is rewritten. This patch cannot recover pixels absent from stored RLE; recovery would require an intact draft, annotation history, or backup, inspected separately with authorization.

Browser regressions compare every decoded RGBA byte across JSON serialization/reopening, pages with different dimensions, multiple masks per page, and the controlled loading-state edit case. Backend regressions cover create, PATCH, PUT, and GET with exact decoded pixel comparisons including disconnected additions and erased holes. Existing webhook rejection/rollback tests remain required. The exact reported normal paint/submit trigger remains unresolved pending testing against affected scans.

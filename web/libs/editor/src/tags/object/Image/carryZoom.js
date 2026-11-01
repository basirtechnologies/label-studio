/**
 * DW-889: keep zoom and position when paging between the images of one multi-image Image tag
 * (`valueList`). Each image entity has its own zoom state and every image load fits the image,
 * so the view is captured from the image being left and applied to the next one after it loads.
 *
 * A view is the zoom scale (screen px per image px, i.e. stageZoom * zoomScale) plus the point of the
 * image at the centre of the viewport, as a fraction of the image size. Keeping the scale means image
 * pixels stay the same size on screen, also when the next image has a different size. Keeping a relative
 * centre gives the same position on images of the same size and the same relative area otherwise; the
 * caller clamps the position with setZoomPosition so the image stays visible.
 */

const EPSILON = 1e-6;

/** How long after applying a carried view a container resize re-applies it (the layout settling). */
export const CARRIED_VIEW_SETTLE_MS = 1000;

/**
 * @param {object} state
 * @param {number} state.currentZoom editor zoom
 * @param {number} state.fitZoom editor zoom of "fit" (Math.max(1, maxScale))
 * @param {number} state.stageZoom stage px per image px
 * @param {number} state.zoomScale stage scale
 * @param {number} state.zoomingPositionX
 * @param {number} state.zoomingPositionY
 * @param {{width: number, height: number}} state.canvasSize viewport the zoom works in
 * @param {number} state.stageWidth
 * @param {number} state.stageHeight
 * @returns {{scale: number, centerX: number, centerY: number} | null} null when the image is at fit
 */
export function captureView({
  currentZoom,
  fitZoom,
  stageZoom,
  zoomScale,
  zoomingPositionX,
  zoomingPositionY,
  canvasSize,
  stageWidth,
  stageHeight,
}) {
  if (!currentZoom || !stageZoom || !zoomScale || !stageWidth || !stageHeight || !canvasSize) return null;
  // at (or below) fit there is nothing to carry over: the next image fits as usual
  if (currentZoom <= fitZoom + EPSILON) return null;

  const centerX = (canvasSize.width / 2 - zoomingPositionX) / zoomScale / stageWidth;
  const centerY = (canvasSize.height / 2 - zoomingPositionY) / zoomScale / stageHeight;

  return { scale: stageZoom * zoomScale, centerX, centerY };
}

/**
 * Editor zoom (the argument of Image#setZoom) that shows an image at `scale` screen px per image px.
 * Mirrors setZoom: an image smaller than the viewport (maxScale > 1) is scaled by the zoom itself,
 * a bigger one by maxScale * zoom. Never below fit.
 * @param {number} scale
 * @param {number} maxScale the image's fit scale (Image#maxScale)
 */
export function editorZoomForScale(scale, maxScale) {
  const zoom = maxScale > 1 ? scale : scale / maxScale;
  return Math.max(zoom, Math.max(1, maxScale));
}

/**
 * Zooming position that puts the view's centre point in the middle of the viewport.
 * The result is not clamped; pass it to Image#setZoomPosition, which keeps the image in view.
 */
export function positionForView(view, { zoomScale, canvasSize, stageWidth, stageHeight }) {
  return {
    x: canvasSize.width / 2 - view.centerX * stageWidth * zoomScale,
    y: canvasSize.height / 2 - view.centerY * stageHeight * zoomScale,
  };
}

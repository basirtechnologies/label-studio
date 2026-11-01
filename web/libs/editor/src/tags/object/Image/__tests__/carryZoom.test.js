/**
 * DW-889: zoom/position carried between the images of a multi-image Image tag (carryZoom.js).
 */
import { CARRIED_VIEW_SETTLE_MS, captureView, editorZoomForScale, positionForView } from "../carryZoom";

const base = {
  currentZoom: 3,
  fitZoom: 1,
  stageZoom: 0.8,
  zoomScale: 3,
  zoomingPositionX: -600,
  zoomingPositionY: -500,
  canvasSize: { width: 960, height: 640 },
  stageWidth: 960,
  stageHeight: 640,
};

describe("captureView", () => {
  it("returns null at fit (nothing to carry, the next image fits as usual)", () => {
    expect(captureView({ ...base, currentZoom: 1, zoomScale: 1, zoomingPositionX: 0, zoomingPositionY: 0 })).toBeNull();
    // small image: fit zoom is maxScale > 1
    expect(captureView({ ...base, currentZoom: 1.25, fitZoom: 1.25 })).toBeNull();
  });

  it("returns null without image geometry", () => {
    expect(captureView({ ...base, stageWidth: 0 })).toBeNull();
    expect(captureView({ ...base, canvasSize: undefined })).toBeNull();
  });

  it("captures the zoom scale (screen px per image px) and the relative centre of the viewport", () => {
    const view = captureView(base);
    expect(view.scale).toBeCloseTo(0.8 * 3, 9);
    // centre of the 960x640 viewport is at stage (480 + 600) / 3 = 360, (320 + 500) / 3 = 273.3
    expect(view.centerX).toBeCloseTo(360 / 960, 9);
    expect(view.centerY).toBeCloseTo(273.333333 / 640, 6);
  });
});

describe("positionForView", () => {
  it("restores the same position on an image of the same size", () => {
    const view = captureView(base);
    const pos = positionForView(view, base);
    expect(pos.x).toBeCloseTo(base.zoomingPositionX, 9);
    expect(pos.y).toBeCloseTo(base.zoomingPositionY, 9);
  });

  it("puts the same relative point in the middle on an image of another size", () => {
    const view = captureView(base);
    const other = { zoomScale: 2.5, canvasSize: { width: 700, height: 875 }, stageWidth: 700, stageHeight: 875 };
    const pos = positionForView(view, other);
    // the stage point at the viewport centre is the same fraction of the new image
    const cx = (other.canvasSize.width / 2 - pos.x) / other.zoomScale / other.stageWidth;
    const cy = (other.canvasSize.height / 2 - pos.y) / other.zoomScale / other.stageHeight;
    expect(cx).toBeCloseTo(view.centerX, 9);
    expect(cy).toBeCloseTo(view.centerY, 9);
  });
});

describe("editorZoomForScale", () => {
  it("image bigger than the viewport (maxScale <= 1): zoom = scale / maxScale", () => {
    expect(editorZoomForScale(2.4, 0.8)).toBeCloseTo(3, 9);
  });

  it("image smaller than the viewport (maxScale > 1): zoom = scale", () => {
    expect(editorZoomForScale(3, 1.25)).toBeCloseTo(3, 9);
  });

  it("never goes below fit", () => {
    expect(editorZoomForScale(0.5, 0.8)).toBe(1);
    expect(editorZoomForScale(1.1, 1.25)).toBe(1.25);
  });
});

it("re-applies only for a short settle window after a page change", () => {
  expect(CARRIED_VIEW_SETTLE_MS).toBeGreaterThan(0);
  expect(CARRIED_VIEW_SETTLE_MS).toBeLessThanOrEqual(2000);
});

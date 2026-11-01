/**
 * Basir DW-890: fixed brush/eraser sizes for the size sliders (and the size shortcuts, DW-891).
 * The sliders move through these values one step at a time; the maximum stays at the previous MAX_SIZE.
 */
export const BRUSH_SIZE_STEPS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 50];

export const MIN_BRUSH_SIZE = BRUSH_SIZE_STEPS[0];
export const MAX_BRUSH_SIZE = BRUSH_SIZE_STEPS[BRUSH_SIZE_STEPS.length - 1];

/**
 * Index of the step closest to `size` (ties go to the smaller step). Sizes that are not a step
 * (e.g. set before steps existed) are shown at the nearest step.
 * @param {number} size
 */
export function stepIndexForSize(size) {
  let best = 0;
  for (let i = 1; i < BRUSH_SIZE_STEPS.length; i++) {
    if (Math.abs(BRUSH_SIZE_STEPS[i] - size) < Math.abs(BRUSH_SIZE_STEPS[best] - size)) best = i;
  }
  return best;
}

/**
 * Size at a slider position, clamped to the steps.
 * @param {number} index
 */
export function sizeAtStep(index) {
  const i = Math.max(0, Math.min(BRUSH_SIZE_STEPS.length - 1, Math.round(index)));
  return BRUSH_SIZE_STEPS[i];
}

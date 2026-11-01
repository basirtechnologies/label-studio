/**
 * DW-890: brush/eraser size steps. DW-891: stepping with the size shortcuts.
 */
import {
  BRUSH_SIZE_STEPS,
  MAX_BRUSH_SIZE,
  MIN_BRUSH_SIZE,
  nextBrushSize,
  sizeAtStep,
  stepIndexForSize,
} from "../brushSizeSteps";

describe("brush size steps", () => {
  it("are the agreed sizes, ascending, from 1 to the previous maximum 50", () => {
    expect(BRUSH_SIZE_STEPS).toEqual([1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 50]);
    expect(MIN_BRUSH_SIZE).toBe(1);
    expect(MAX_BRUSH_SIZE).toBe(50);
  });

  it("include the default brush (15) and eraser (10) sizes", () => {
    expect(BRUSH_SIZE_STEPS).toContain(15);
    expect(BRUSH_SIZE_STEPS).toContain(10);
  });

  it("map every step to its own index and back", () => {
    BRUSH_SIZE_STEPS.forEach((size, index) => {
      expect(stepIndexForSize(size)).toBe(index);
      expect(sizeAtStep(index)).toBe(size);
    });
  });

  it("map other sizes to the nearest step (ties to the smaller one)", () => {
    expect(stepIndexForSize(12)).toBe(5); // 10
    expect(stepIndexForSize(13)).toBe(6); // 15
    expect(stepIndexForSize(25)).toBe(7); // 20 (tie between 20 and 30)
    expect(stepIndexForSize(0)).toBe(0);
    expect(stepIndexForSize(100)).toBe(BRUSH_SIZE_STEPS.length - 1);
  });

  it("clamp and round slider positions", () => {
    expect(sizeAtStep(-3)).toBe(1);
    expect(sizeAtStep(99)).toBe(50);
    expect(sizeAtStep(6.4)).toBe(15);
  });
});

describe("nextBrushSize (DW-891)", () => {
  it("walks through every step up and down, one at a time", () => {
    let size = MIN_BRUSH_SIZE;
    const up = [size];
    for (let i = 0; i < BRUSH_SIZE_STEPS.length - 1; i++) up.push((size = nextBrushSize(size, 1)));
    expect(up).toEqual(BRUSH_SIZE_STEPS);
    const down = [size];
    for (let i = 0; i < BRUSH_SIZE_STEPS.length - 1; i++) down.push((size = nextBrushSize(size, -1)));
    expect(down).toEqual([...BRUSH_SIZE_STEPS].reverse());
  });

  it("stays at the ends", () => {
    expect(nextBrushSize(MIN_BRUSH_SIZE, -1)).toBe(MIN_BRUSH_SIZE);
    expect(nextBrushSize(MAX_BRUSH_SIZE, 1)).toBe(MAX_BRUSH_SIZE);
  });

  it("moves a size that is not a step to the neighbouring step", () => {
    expect(nextBrushSize(12, 1)).toBe(15);
    expect(nextBrushSize(12, -1)).toBe(10);
    expect(nextBrushSize(0, 1)).toBe(1);
    expect(nextBrushSize(80, -1)).toBe(50);
  });
});

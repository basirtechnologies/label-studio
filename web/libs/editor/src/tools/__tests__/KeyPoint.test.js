/**
 * Unit tests for KeyPoint tool (tools/KeyPoint.js).
 * DW-888 regression: a click outside the image (in the canvas area the image doesn't cover) creates nothing.
 */
import { getRoot } from "mobx-state-tree";

beforeEach(() => {
  getRoot.mockImplementation((node) => {
    if (node && typeof node === "object" && Object.hasOwn(node, "__mockRoot")) {
      return node.__mockRoot;
    }
    return globalThis.__mstOriginals.getRoot(node);
  });
});

const { KeyPoint } = require("../KeyPoint");

describe("KeyPoint tool", () => {
  let annotation;
  let control;
  let obj;

  function createTool() {
    return KeyPoint.create({}, { manager: { name: "kp", selectTool: mock() }, control, object: obj });
  }

  function mockRegionCreation(tool) {
    const region = { setDrawing: mock(), notifyDrawingFinished: mock() };
    const spy = spyOn(tool, "createRegion").mockReturnValue(region);
    return { spy, region };
  }

  beforeEach(() => {
    clearAllMocks();
    annotation = { isReadOnly: () => false, isDrawing: false };
    control = {
      type: "keypointlabels",
      isSelected: true,
      strokewidth: "2",
      getSnappedPoint: (p) => p,
      annotation,
    };
    // a 400px-wide image on a wider canvas: the canvas (image) area ends at x=400, y=800
    obj = {
      name: "pages",
      canvasSize: { width: 400, height: 800 },
      canvasToInternalX: (v) => v,
      checkLabels: () => true,
      annotation,
    };
    control.__mockRoot = { annotationStore: { selected: annotation }, settings: {} };
    obj.__mockRoot = { annotationStore: { selected: annotation }, settings: {} };
  });

  it("is a segmentation tool, so clicks are checked against the image bounds", () => {
    expect(createTool().group).toBe("segmentation");
  });

  it("creates a keypoint for a click inside the image", () => {
    const tool = createTool();
    const { spy, region } = mockRegionCreation(tool);
    tool.clickEv({ offsetX: 395, offsetY: 300 }, [98.75, 37.5]);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(region.notifyDrawingFinished).toHaveBeenCalled();
  });

  it.each([
    ["right of the image", { offsetX: 401, offsetY: 300 }],
    ["below the image", { offsetX: 100, offsetY: 801 }],
    ["right of and below the image", { offsetX: 650, offsetY: 900 }],
  ])("creates nothing for a click %s", (_where, ev) => {
    const tool = createTool();
    const { spy } = mockRegionCreation(tool);
    tool.clickEv(ev, [150, 120]);
    expect(spy).not.toHaveBeenCalled();
  });
});

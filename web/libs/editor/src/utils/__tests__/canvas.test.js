/* global describe, test, expect, mock, spyOn, beforeEach */
import { encode as rleEncode } from "@thi.ng/rle-pack";
import Canvas from "../canvas";

const svgs = {
  simple: [
    "'data:image/svg+xml,",
    '%3Csvg xmlns="http://www.w3.org/2000/svg" height="16" width="2"%3E',
    '%3Ctext x="0" y="11" style="font-size: 9.5px; font-weight: bold; font-family: var(--font-mono);"%3E',
    "Test Label",
    "%3C/text%3E%3C/svg%3E'",
  ].join(""),
  complex: [
    "'data:image/svg+xml,",
    '%3Csvg xmlns="http://www.w3.org/2000/svg" height="16" width="2"%3E',
    '%3Ctext x="0" y="11" style="font-size: 9.5px; font-weight: bold; font-family: var(--font-mono);"%3E',
    "A&lt;/text%3E B",
    "%3C/text%3E%3C/svg%3E'",
  ].join(""),
  score: [
    "'data:image/svg+xml,",
    '%3Csvg xmlns="http://www.w3.org/2000/svg" height="16" width="28"%3E',
    '%3Crect x="0" y="0" rx="2" ry="2" width="24" height="14" style="fill:%237ca91f;opacity:0.5" /%3E',
    '%3Ctext x="3" y="10" style="font-size: 8px; font-family: var(--font-mono);"%3E0.60%3C/text%3E',
    '%3Ctext x="26" y="11" style="font-size: 9.5px; font-weight: bold; font-family: var(--font-mono);"%3E',
    "Test Label",
    "%3C/text%3E%3C/svg%3E'",
  ].join(""),
  empty: [
    "'data:image/svg+xml,",
    '%3Csvg xmlns="http://www.w3.org/2000/svg" height="16" width="0"%3E',
    "%3C/svg%3E'",
  ].join(""),
};

describe("Helper function labelToSVG", () => {
  test("Simple label", () => {
    expect(Canvas.labelToSVG({ label: "Test Label" })).toBe(svgs.simple);
  });

  test("Complex label", () => {
    // labels will be already escaped
    expect(Canvas.labelToSVG({ label: "A&lt;/text>   B" })).toBe(svgs.complex);
  });

  test("With score", () => {
    expect(Canvas.labelToSVG({ label: "Test Label", score: 0.6 })).toBe(svgs.score);
  });

  test("No label & score", () => {
    expect(Canvas.labelToSVG({})).toBe(svgs.empty);
  });

  test("label with score null uses cache key without score", () => {
    const out1 = Canvas.labelToSVG({ label: "L", score: null });
    const out2 = Canvas.labelToSVG({ label: "L", score: null });
    expect(out1).toBe(out2);
  });
});

describe("createBrushSizeCircleCursor", () => {
  test("returns cursor CSS string with data URL and hotspot", () => {
    const result = Canvas.createBrushSizeCircleCursor(24);
    expect(result).toMatch(/^url\('/);
    expect(result).toContain(",");
    expect(result).toContain("auto");
  });

  // DW-886: the canvas must not truncate a fractional diameter, and the hotspot is the circle center
  test.each([
    [15, 23, 11],
    [32.95, 41, 20],
    [120, 128, 64],
  ])("diameter %p gives a %p px image with hotspot %p", (diameter, imageSize, hotspot) => {
    const created = [];
    const realCreate = document.createElement.bind(document);
    const spy = spyOn(document, "createElement").mockImplementation((tag) => {
      const el = realCreate(tag);
      if (tag === "canvas") created.push(el);
      return el;
    });
    try {
      const result = Canvas.createBrushSizeCircleCursor(diameter);
      expect(created[0].width).toBe(imageSize);
      expect(created[0].height).toBe(imageSize);
      expect(result.endsWith(`') ${hotspot} ${hotspot}, auto`)).toBe(true);
    } finally {
      spy.mockRestore();
    }
  });
});

describe("isSinglePointPath / strokeBrushPath (DW-887)", () => {
  const makeCtx = () => ({
    beginPath: mock(),
    moveTo: mock(),
    lineTo: mock(),
    stroke: mock(),
    arc: mock(),
    fill: mock(),
    lineWidth: 16,
    strokeStyle: "rgba(255,0,0,0.7)",
    fillStyle: "",
  });

  test("detects a path without length", () => {
    expect(Canvas.isSinglePointPath([5, 7])).toBe(true);
    expect(Canvas.isSinglePointPath([5, 7, 5, 7, 5, 7])).toBe(true);
    expect(Canvas.isSinglePointPath([5, 7, 6, 7])).toBe(false);
    expect(Canvas.isSinglePointPath([5, 7, 5, 7, 5, 8])).toBe(false);
    expect(Canvas.isSinglePointPath([])).toBe(false);
  });

  test("paints a single point as a dot of the brush diameter", () => {
    const ctx = makeCtx();
    Canvas.strokeBrushPath(ctx, [30, 40, 30, 40]);
    expect(ctx.arc).toHaveBeenCalledWith(30, 40, 8, 0, 2 * Math.PI);
    expect(ctx.fillStyle).toBe("rgba(255,0,0,0.7)");
    expect(ctx.fill).toHaveBeenCalledTimes(1);
    expect(ctx.stroke).not.toHaveBeenCalled();
  });

  test("strokes a path with length as before", () => {
    const ctx = makeCtx();
    Canvas.strokeBrushPath(ctx, [30, 40, 31, 40, 50, 60]);
    expect(ctx.moveTo).toHaveBeenCalledWith(30, 40);
    expect(ctx.lineTo).toHaveBeenNthCalledWith(1, 31, 40);
    expect(ctx.lineTo).toHaveBeenNthCalledWith(2, 50, 60);
    expect(ctx.stroke).toHaveBeenCalledTimes(1);
    expect(ctx.arc).not.toHaveBeenCalled();
  });

  test("does nothing for an empty path", () => {
    const ctx = makeCtx();
    Canvas.strokeBrushPath(ctx, []);
    expect(ctx.beginPath).not.toHaveBeenCalled();
  });
});

describe("brushCursorFitsCss", () => {
  test("fits up to the 128px browser cursor limit, padding included", () => {
    expect(Canvas.MAX_CSS_CURSOR_SIZE).toBe(128);
    expect(Canvas.brushCursorFitsCss(15)).toBe(true);
    expect(Canvas.brushCursorFitsCss(120)).toBe(true);
    expect(Canvas.brushCursorFitsCss(120.2)).toBe(false);
    expect(Canvas.brushCursorFitsCss(500)).toBe(false);
  });
});

describe("trim", () => {
  test("returns bbox and canvas from canvas with opaque pixels", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 10;
    canvas.height = 10;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(1,1,1,1)";
    ctx.fillRect(2, 2, 4, 4);
    const result = Canvas.trim(canvas);
    expect(result).toHaveProperty("bbox");
    expect(result.bbox).toHaveProperty("width");
    expect(result.bbox).toHaveProperty("height");
    expect(result).toHaveProperty("canvas");
  });

  test("returns canvas and bbox when canvas is fully transparent", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 10;
    canvas.height = 10;
    const result = Canvas.trim(canvas);
    expect(result).toHaveProperty("bbox");
    expect(result).toHaveProperty("canvas");
    expect(result.canvas).toBeTruthy();
    expect(result.canvas.width).toBeGreaterThanOrEqual(0);
    expect(result.canvas.height).toBeGreaterThanOrEqual(0);
  });

  test("returns fallback when getImageData throws (catch branch)", () => {
    const fakeCanvas = {
      width: 10,
      height: 10,
      getContext: () => ({
        getImageData: () => {
          throw new Error("mock throw");
        },
      }),
    };
    const result = Canvas.trim(fakeCanvas);
    expect(result).toHaveProperty("bbox");
    expect(result).toHaveProperty("canvas");
    expect(result.canvas).toBeTruthy();
  });
});

describe("mask2DataURL", () => {
  test("returns data URL from single-channel mask (mocked canvas.toDataURL)", () => {
    const singleChannel = new Uint8ClampedArray(4);
    singleChannel[0] = 255;
    singleChannel[3] = 255;
    const putImageData = mock();
    const getImageData = mock().mockReturnValue({
      data: new Uint8ClampedArray(16),
    });
    const toDataURL = mock().mockReturnValue("data:image/png;base64,stub");
    const canvas = {
      width: 2,
      height: 2,
      getContext: () => ({
        getImageData,
        putImageData,
      }),
      toDataURL,
    };
    const origCreateElement = document.createElement.bind(document);

    spyOn(document, "createElement").mockImplementation((tag) => (tag === "canvas" ? canvas : origCreateElement(tag)));

    const url = Canvas.mask2DataURL(singleChannel, 2, 2, "#ff0000");

    expect(toDataURL).toHaveBeenCalled();
    expect(url).toBe("data:image/png;base64,stub");
    expect(putImageData).toHaveBeenCalled();

    restoreAllMocks();
  });
});

describe("maskDataURL2Image", () => {
  test("resolves with image after processing mask data URL (mocked canvas/img)", async () => {
    const putImageData = mock();
    const getImageData = mock().mockReturnValue({
      data: new Uint8ClampedArray(16),
    });
    const toDataURL = mock().mockReturnValue("data:image/png;base64,out");
    const canvasStub = {
      width: 2,
      height: 2,
      getContext: () => ({
        getImageData,
        putImageData,
        drawImage: mock(),
      }),
      toDataURL,
    };
    let storedOnload;
    let triggerOnload = true;
    const imgStub = {
      set onload(fn) {
        storedOnload = fn;
      },
      set src(_value) {
        if (storedOnload && triggerOnload) {
          triggerOnload = false;
          setTimeout(storedOnload, 0);
        }
      },
      width: 2,
      height: 2,
    };
    const origCreateElement = document.createElement.bind(document);
    spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "canvas") return canvasStub;
      if (tag === "img") return imgStub;
      return origCreateElement(tag);
    });

    const result = await Canvas.maskDataURL2Image("data:image/png;base64,stub", { color: "#00ff00" });

    expect(result).toBe(imgStub);
    expect(putImageData).toHaveBeenCalled();
    expect(toDataURL).toHaveBeenCalled();
    restoreAllMocks();
  });
});

describe("RLE2Region", () => {
  test("returns Image with data URL from RLE-encoded item", () => {
    const nw = 2;
    const nh = 2;
    const raw = new Uint8Array(nw * nh * 4);
    raw[3] = 255;
    raw[7] = 255;
    const rle = rleEncode(raw, raw.length);
    const imageData = { data: new Uint8ClampedArray(nw * nh * 4) };
    const putImageData = mock();
    const toDataURL = mock().mockReturnValue("data:image/png;base64,rle2region");
    const canvas = {
      width: nw,
      height: nh,
      getContext: () => ({
        createImageData: () => imageData,
        putImageData,
        getImageData: () => imageData,
      }),
      toDataURL,
    };
    const origCreateElement = document.createElement.bind(document);

    spyOn(document, "createElement").mockImplementation((tag) => (tag === "canvas" ? canvas : origCreateElement(tag)));

    const item = {
      rle,
      currentImageEntity: { naturalWidth: nw, naturalHeight: nh },
    };
    const result = Canvas.RLE2Region(item, { color: "#ff0000" });

    expect(result).toBeInstanceOf(Image);
    expect(result.src).toBe("data:image/png;base64,rle2region");
    expect(putImageData).toHaveBeenCalled();
    restoreAllMocks();
  });

  test("accepts custom color option", () => {
    const nw = 2;
    const nh = 2;
    const raw = new Uint8Array(16);
    raw[3] = 255;
    const rle = rleEncode(raw, raw.length);
    const imageData = { data: new Uint8ClampedArray(16) };
    const canvas = {
      width: nw,
      height: nh,
      getContext: () => ({
        createImageData: () => imageData,
        putImageData: mock(),
        getImageData: () => imageData,
      }),
      toDataURL: () => "data:image/png;base64,default",
    };
    const origCreateElement = document.createElement.bind(document);

    spyOn(document, "createElement").mockImplementation((tag) => (tag === "canvas" ? canvas : origCreateElement(tag)));

    const item = {
      rle,
      currentImageEntity: { naturalWidth: nw, naturalHeight: nh },
    };
    const result = Canvas.RLE2Region(item, { color: "#888" });

    expect(result).toBeInstanceOf(Image);
    expect(result.src).toBe("data:image/png;base64,default");
    restoreAllMocks();
  });
});

const realCreateElement = document.createElement.bind(document);

function createExportRLECanvas(nw, nh) {
  const canvas = realCreateElement("canvas");
  canvas.width = nw;
  canvas.height = nh;
  if (!canvas.style) canvas.style = {};
  if (typeof canvas.style.setProperty !== "function") {
    canvas.style.setProperty = mock();
  }
  const imageData = { data: new Uint8ClampedArray(nw * nh * 4) };
  const ctx = {
    createImageData: () => ({ data: new Uint8ClampedArray(nw * nh * 4) }),
    putImageData: mock(),
    drawImage: mock(),
    getImageData: () => imageData,
    save: mock(),
    restore: mock(),
    beginPath: mock(),
    moveTo: mock(),
    lineTo: mock(),
    stroke: mock(),
    arc: mock(),
    fill: mock(),
  };
  canvas.getContext = () => ctx;
  canvas.__ctx = ctx;
  return canvas;
}

describe("Region2RLE", () => {
  test("returns RLE (exportRLE path)", () => {
    const origCreateElement = document.createElement.bind(document);
    spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "canvas") return createExportRLECanvas(4, 4);
      return origCreateElement(tag);
    });
    const region = {
      currentImageEntity: { naturalWidth: 4, naturalHeight: 4 },
      rle: null,
      touches: [],
    };
    const result = Canvas.Region2RLE(region);
    expect(result).toBeDefined();
    expect(Array.isArray(result) || typeof result === "string" || ArrayBuffer.isView(result)).toBe(true);
    restoreAllMocks();
  });

  test("exportRLE path with existing region.rle applies decode and putImageData", () => {
    const nw = 4;
    const nh = 4;
    const raw = new Uint8Array(nw * nh * 4);
    raw[15] = 255;
    const rle = rleEncode(raw, raw.length);
    const putImageData = mock();
    const imageDataForGet = { data: new Uint8ClampedArray(nw * nh * 4) };
    const realCanvas = createExportRLECanvas(nw, nh);
    realCanvas.getContext = () => ({
      createImageData: () => ({ data: new Uint8ClampedArray(nw * nh * 4) }),
      putImageData,
      drawImage: mock(),
      getImageData: () => imageDataForGet,
    });
    const origCreateElement = document.createElement.bind(document);

    spyOn(document, "createElement").mockImplementation((tag) =>
      tag === "canvas" ? realCanvas : origCreateElement(tag),
    );

    const region = {
      currentImageEntity: { naturalWidth: nw, naturalHeight: nh },
      rle,
      touches: [],
    };
    const result = Canvas.Region2RLE(region);

    expect(result).toBeDefined();
    expect(putImageData).toHaveBeenCalled();
    restoreAllMocks();
  });

  test("exportRLE path with getMaskImage draws mask on canvas", () => {
    const origCreateElement = document.createElement.bind(document);
    spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "canvas") return createExportRLECanvas(4, 4);
      return origCreateElement(tag);
    });
    const maskCanvas = document.createElement("canvas");
    maskCanvas.width = 4;
    maskCanvas.height = 4;
    const region = {
      currentImageEntity: { naturalWidth: 4, naturalHeight: 4 },
      rle: null,
      touches: [],
      getMaskImage: () => maskCanvas,
    };
    const result = Canvas.Region2RLE(region);
    expect(result).toBeDefined();
    restoreAllMocks();
  });

  // DW-887: a click without movement must end up in the saved mask as a dot of the brush size
  test.each([
    ["brush", "source-over"],
    ["eraser", "destination-out"],
  ])("a single-click %s touch is painted as a dot into the mask", (_tool, compositeOperation) => {
    const origCreateElement = document.createElement.bind(document);
    let exportCanvas;
    spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "canvas") return (exportCanvas = createExportRLECanvas(200, 100));
      return origCreateElement(tag);
    });
    const region = {
      currentImageEntity: { naturalWidth: 200, naturalHeight: 100 },
      rle: null,
      touches: [
        {
          toJSON: () => ({ relativePoints: [25, 50, 25, 50] }),
          relativeStrokeWidth: 10, // 10% of 200px = 20px brush
          compositeOperation,
        },
      ],
    };
    Canvas.Region2RLE(region);
    const ctx = exportCanvas.__ctx;
    // centre (50px, 50px), radius = half the 20px brush
    expect(ctx.arc).toHaveBeenCalledWith(50, 50, 10, 0, 2 * Math.PI);
    expect(ctx.fill).toHaveBeenCalled();
    expect(ctx.stroke).not.toHaveBeenCalled();
    expect(ctx.globalCompositeOperation).toBe(compositeOperation);
    restoreAllMocks();
  });

  test("exportRLE path with touches renders strokes and encodes", () => {
    const origCreateElement = document.createElement.bind(document);
    spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "canvas") return createExportRLECanvas(10, 10);
      return origCreateElement(tag);
    });
    const region = {
      currentImageEntity: { naturalWidth: 10, naturalHeight: 10 },
      rle: null,
      touches: [
        {
          toJSON: () => ({ relativePoints: [0, 0, 50, 50, 100, 0] }),
          relativeStrokeWidth: 10,
          compositeOperation: "source-over",
        },
      ],
    };
    const result = Canvas.Region2RLE(region);
    expect(result).toBeDefined();
    restoreAllMocks();
  });
});

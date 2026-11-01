import { decode, encode } from "@thi.ng/rle-pack";
import chroma from "chroma-js";
import Constants from "../core/Constants";

import * as Colors from "./colors";

/**
 * Given a single channel UInt8 image data mask with non-zero values indicating the
 * mask, turn it into a 4 channgel RGBA image data URL filled in with the given
 * color for pixels turned on in the mask.
 * @param {ImageData} Single channel image mask data.
 * @param {number} w Width of the resulting image data URL.
 * @param {number} h Height of the resulting image data URL.
 * @param {string} color Hex color of the resulting mask image.
 * @returns {string} Data URL containing the mask as an image.
 */
function mask2DataURL(singleChannelData, w, h, color) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");

  canvas.width = w;
  canvas.height = h;

  const numChannels = 1;

  setMaskPixelColors(ctx, singleChannelData, w, h, color, numChannels);

  const url = canvas.toDataURL();

  return url;
}

/**
 * Given an RGBA image data URL, turn it into an actual DOM Image filled in with the current
 * class color.
 * @param {string} maskDataURL Data URL, such as returned from mask2DataURL, containing
 *  an image.
 * @param {string} color The fill color of the image produced from the Data URL.
 * @returns {Promise<Image>} DOM Image filled out with the resulting mask data URL.
 */
function maskDataURL2Image(maskDataURL, { color = Constants.FILL_COLOR } = {}) {
  return new Promise((resolve, _reject) => {
    const img = document.createElement("img");

    img.onload = () => {
      const canvas = document.createElement("canvas");
      const nw = img.width;
      const nh = img.height;

      canvas.width = nw;
      canvas.height = nh;

      const ctx = canvas.getContext("2d");

      ctx.drawImage(img, 0, 0);

      const imgData = ctx.getImageData(0, 0, nw, nh);

      const numChannels = 4; // RGBA

      setMaskPixelColors(ctx, imgData.data, nw, nh, color, numChannels);

      img.src = canvas.toDataURL();

      resolve(img);
    };
    img.src = maskDataURL;
  });
}

/**
 * Given some RGBA mask pixel array, efficiently sets the colors. Note that we assume that the same value is set
 * throughout the channels of the mask, so that no channel will be set to 0 if there is a valid mask
 * position there (i.e. all channels might be 255 if a mask is present).
 * @param {CanvasRenderingContext2D} ctx DOM canvas surface to draw on.
 * @param {ImageData} Raw canvas.getImageData() to work with.
 * @param {number} nw The natural width (i.e. the true width of the canvas independent of how its being displayed).
 * @param {number} nh Similar, but the natural height.
 * @param {string} color Hex string color to use for mask, such as '#ff8800'.
 * @param {number} numChannels The source image could either be a 1-channel mask, or
 *  a full color 4-channel RGBA image.
 */
function setMaskPixelColors(ctx, data, nw, nh, color, numChannels) {
  const [red, green, blue] = chroma(color).rgb();
  const alpha = 255;

  // Efficently expand the single channel mask to be multi-channel by treating the
  // target array as single 32-bit numbers, so that the RGBA values can be set in
  // a single machine instruction via bit-shifting in a performance conscious way.
  const resultsData = ctx.getImageData(0, 0, nw, nh);
  const buffer = new ArrayBuffer(nw * nh * 4); // RGBA
  const dataView = new Uint32Array(buffer);
  const expandedView = new Uint8ClampedArray(buffer);

  // Clamped arrays have different byte endian ordering for different platforms,
  // effecting the order in which we set 8-bit colors via 32-bit values.
  const endian = checkEndian();
  let finalColor;

  if (endian === "little endian") {
    finalColor = (alpha << 24) | (blue << 16) | (green << 8) | red;
  } else if (endian === "big endian") {
    finalColor = (red << 24) | (green << 16) | (blue << 8) | alpha;
  } else {
    // The most common architectures (x86 and ARM) are both little endian, so just assume that.
    console.error(`Unknown platform endianness (${endian}), assuming little endian`);
    finalColor = (alpha << 24) | (blue << 16) | (green << 8) | red;
  }

  let x;
  let y;
  const sourceNumChannels = numChannels; // Could be 1-channel mask or RGBA mask.

  for (y = 0; y < nh; y++) {
    for (x = 0; x < nw; x++) {
      // The source is UInt8, while the target is UInt32.
      // This means indexing the source should be multiplied by the number
      // of channels, while for the target every 32-bit entry contains the full
      // RGBA value so we can index into it directly.
      const idx = y * nw + x;

      if (data[idx * sourceNumChannels]) {
        // If the mask is set at this position...
        dataView[idx] = finalColor;
      }
    }
  }

  resultsData.data.set(expandedView);
  ctx.putImageData(resultsData, 0, 0);
}

/**
 * Given the RLE array returns the DOM Image element with loaded image.
 * @param {string} rle RLE encoded image to be turned into a Region object.
 * @param {tags.object.Image} image Image the region will be interacting with.
 * @param {string} color Fill color for the region that will be produced.
 * @returns {Image} DOM image filled in with RLE contents.
 */
function RLE2Region(item, { color = Constants.FILL_COLOR } = {}) {
  const { rle } = item;
  const nw = item.currentImageEntity.naturalWidth;
  const nh = item.currentImageEntity.naturalHeight;

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");

  canvas.width = nw;
  canvas.height = nh;

  const newdata = ctx.createImageData(nw, nh);
  const decoded = decode(rle);

  newdata.data.set(decoded, 0);

  const rgb = chroma(color).rgb();

  for (let i = newdata.data.length / 4; i--; ) {
    if (newdata.data[i * 4 + 3]) {
      newdata.data[i * 4] = rgb[0];
      newdata.data[i * 4 + 1] = rgb[1];
      newdata.data[i * 4 + 2] = rgb[2];
    }
  }

  ctx.putImageData(newdata, 0, 0);

  const new_image = new Image();

  new_image.src = canvas.toDataURL();
  return new_image;
}

/**
 * Exports region using canvas. Doesn't require Konva#Stage access
 * @param {Region} region Brush region
 */
function exportRLE(region) {
  const { naturalWidth, naturalHeight } = region.currentImageEntity;

  // Prepare the canvas with sizes of image and stage
  const canvas = document.createElement("canvas");

  // We only care about physical size, so set canvas dimensions to
  // image's natural dimensions
  canvas.width = naturalWidth;
  canvas.height = naturalHeight;

  // Make canvas offscreen and invisible
  canvas.style.setProperty("position", "absolute");
  canvas.style.setProperty("bottom", "200%");
  canvas.style.setProperty("right", "200%");
  canvas.style.setProperty("opacity", "0");

  const ctx = canvas.getContext("2d");

  document.body.appendChild(canvas);

  // Restore original RLE if available
  if (region.rle && region.rle.length > 0) {
    // Apply RLE to existing image data
    const imageData = ctx.createImageData(naturalWidth, naturalHeight);

    imageData.data.set(decode(region.rle));

    ctx.putImageData(imageData, 0, 0);
  }

  const maskImage = region.getMaskImage?.();

  if (maskImage) {
    // Apply maskDataURL to existing image data
    ctx.drawImage(maskImage, 0, 0);
  }

  // If the region was changed manually, we'll have access to user tuoches
  // Render those on the canvas after RLE
  if (region.touches.length > 0) {
    region.touches.forEach((touch) => {
      // We're using relative coordinates to calculate points
      // This way we don't need to have access to Konva#Stage and
      // render relatively to the image's natural dimensions
      const { relativePoints: points } = touch.toJSON();

      /**
       * Converts any given relative (x, y) to absolute position on an image
       * @param {number} x
       * @param {number} y
       */
      const relativeToAbsolutePoint = (x, y) => {
        return [naturalWidth * (x / 100), naturalHeight * (y / 100)];
      };

      ctx.save();
      ctx.strokeStyle = "#000";
      ctx.lineWidth = (touch.relativeStrokeWidth / 100) * naturalWidth;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.globalCompositeOperation = touch.compositeOperation;
      const absolutePoints = [];
      for (let i = 0; i < points.length; i += 2) {
        absolutePoints.push(...relativeToAbsolutePoint(points[i], points[i + 1]));
      }
      // a single click (no movement) is painted as a dot instead of being dropped
      strokeBrushPath(ctx, absolutePoints);
      ctx.restore();
    });
  }

  const imageData = ctx.getImageData(0, 0, naturalWidth, naturalHeight).data;

  // Grayscale pixels respecting the opacity
  for (let i = imageData.length / 4; i--; ) {
    imageData[i * 4] = imageData[i * 4 + 1] = imageData[i * 4 + 2] = imageData[i * 4 + 3];
  }

  // When finished, remove the canvas
  canvas.remove();

  return encode(imageData, imageData.length);
}

/**
 * Given a brush region return the RLE encoded array.
 * @param {BrushRegion} region BrushRegtion to turn into RLE array.
 * @param {tags.object.Image} image Image the region will be interacting with.
 * @returns {string} RLE encoded contents.
 */
function Region2RLE(region) {
  return exportRLE(region);
}

/**
 * Creates a custom circular cursor visual representation based on the provided brush size.
 * Max size: 128px according to browser limitations.
 *
 * @param {number} size - The diameter of the brush in pixels.
 * Determines the size of the circular cursor.
 * @return {string} A CSS-compatible string for setting the custom cursor,
 * including a data URL with the cursor image and its hotspot coordinates.
 */
/**
 * Whether a flat [x0, y0, x1, y1, ...] brush path has no length (every point is the same point),
 * which is what a click without mouse movement produces.
 * @param {number[]} points
 */
function isSinglePointPath(points) {
  if (!points || points.length < 2) return false;
  for (let i = 2; i < points.length; i += 2) {
    if (points[i] !== points[0] || points[i + 1] !== points[1]) return false;
  }
  return true;
}

/**
 * Stroke a brush/eraser path with the context's current lineWidth, strokeStyle and composite operation.
 * Canvas prunes zero-length segments before stroking, so a single click would paint nothing; such a
 * path is painted as a dot of the brush diameter instead, exactly what a stroke's round cap would draw.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number[]} points flat [x0, y0, x1, y1, ...] in the context's coordinates
 */
function strokeBrushPath(ctx, points) {
  if (!points || points.length < 2) return;
  ctx.beginPath();
  if (isSinglePointPath(points)) {
    ctx.arc(points[0], points[1], ctx.lineWidth / 2, 0, 2 * Math.PI);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fill();
    return;
  }
  ctx.moveTo(points[0], points[1]);
  for (let i = 2; i < points.length; i += 2) {
    ctx.lineTo(points[i], points[i + 1]);
  }
  ctx.stroke();
}

// Browsers ignore CSS cursor images larger than 128x128 px and fall back to the default cursor
const MAX_CSS_CURSOR_SIZE = 128;
// The circle outline (3px) plus 1px reserve on each side of the diameter
const BRUSH_CURSOR_PADDING = (3 + 1) * 2;

/**
 * Whether a brush cursor circle of this diameter (CSS px) fits into a CSS cursor image.
 * Bigger circles have to be drawn on the canvas instead (see BrushCursorLayer in ImageView).
 * @param {number} diameter
 */
function brushCursorFitsCss(diameter) {
  return Math.ceil(diameter) + BRUSH_CURSOR_PADDING <= MAX_CSS_CURSOR_SIZE;
}

function createBrushSizeCircleCursor(size) {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const strokeWidth = 3;
  // Canvas sizes are integers: round the diameter up instead of letting the canvas truncate it,
  // so the drawn circle keeps its exact (fractional) diameter in the middle of the image
  const canvasSize = Math.ceil(size) + BRUSH_CURSOR_PADDING;
  // Position the circle in the center of the canvas
  const circlePos = canvasSize / 2;
  const circleRadius = size / 2;

  canvas.width = canvasSize;
  canvas.height = canvasSize;

  ctx.beginPath();
  ctx.arc(circlePos, circlePos, circleRadius, 0, 2 * Math.PI, false);

  ctx.lineWidth = strokeWidth;
  ctx.strokeStyle = "black";
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(circlePos, circlePos, circleRadius, 0, 2 * Math.PI, false);

  ctx.lineWidth = strokeWidth - 1;
  ctx.strokeStyle = "white";
  ctx.stroke();

  const base64 = canvas.toDataURL();
  // the hotspot must be an integer
  const hotspot = Math.floor(circlePos);
  return `url('${base64}') ${hotspot} ${hotspot}, auto`;
}

/**
 * Given a string of SVG xml, encode it into a data URL
 * @param {string} data SVG XML string to encode
 * @returns {string} Data URL containing inline SVG already enclosed in quotes
 */
function encodeSVG(data) {
  data = data.replace(/\s{2,}/g, " ");

  const symbols = /[\r\n%#()<>?[\\\]^`{|}]/g;
  const escaped = data.replace(symbols, encodeURIComponent);

  return `'data:image/svg+xml,${escaped}'`;
}

/**
 * Given a label and optional score, return an SVG data URL to use it in regions.
 * Has internal caching to avoid recalculating the same SVGs.
 * @param {string} label Label text
 * @param {number} [score] Score in [0, 1] range
 * @returns {string} Data URL containing inline SVG already enclosed in quotes
 */
const labelToSVG = (() => {
  const SVG_CACHE = {};

  function calculateTextWidth(text) {
    const svg = document.createElement("svg");
    const svgText = document.createElement("text");

    svgText.style = "font-size: 9.5px; font-weight: bold; color: red; fill: red; font-family: var(--font-mono);";
    svgText.innerHTML = text;

    svg.appendChild(svgText);
    document.body.appendChild(svg);

    const textLen = svgText.getBoundingClientRect().width;

    svg.remove();

    return textLen;
  }

  return ({ label, score }) => {
    let cacheKey = label;

    if (score !== null) cacheKey = cacheKey + score;

    if (cacheKey in SVG_CACHE) return SVG_CACHE[cacheKey];

    let width = 0;
    const items = [];

    if (score !== null && score !== undefined) {
      const fillColor = Colors.getScaleGradient(score);

      items.push(`<rect x="0" y="0" rx="2" ry="2" width="24" height="14" style="fill:${fillColor};opacity:0.5" />`);
      items.push(
        `<text x="3" y="10" style="font-size: 8px; font-family: var(--font-mono);">${score.toFixed(2)}</text>`,
      );
      width = width + 26;
    }

    if (label) {
      items.push(
        `<text x="${width}" y="11" style="font-size: 9.5px; font-weight: bold; font-family: var(--font-mono);">${label}</text>`,
      );
      width = width + calculateTextWidth(label) + 2;
    }

    const xmlns = 'xmlns="http://www.w3.org/2000/svg"';
    const res = `<svg ${xmlns} height="16" width="${width}">${items.join("")}</svg>`;
    const enc = encodeSVG(res);

    SVG_CACHE[cacheKey] = enc;
    return enc;
  };
})();

/**
 *
 * @param {HTMLCanvasElement} canvas
 * @returns {{
 * canvas: HTMLCanvasElement,
 * bbox: {
 *   left: number,
 *   top: number,
 *   right: number,
 *   bottom: number,
 *   width: number,
 *   height: number
 * }
 * }}
 */
const trim = (canvas) => {
  let copy;
  let width = canvas.width;
  let height = canvas.height;
  const ctx = canvas.getContext("2d");
  const bbox = {
    top: null,
    left: null,
    right: null,
    bottom: null,
  };

  try {
    copy = document.createElement("canvas").getContext("2d");
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const l = pixels.data.length;
    let i;
    let x;
    let y;

    for (i = 0; i < l; i += 4) {
      if (pixels.data[i + 3] !== 0) {
        x = (i / 4) % canvas.width;
        y = ~~(i / 4 / canvas.width);

        if (bbox.top === null) {
          bbox.top = y;
        }

        if (bbox.left === null) {
          bbox.left = x;
        } else if (x < bbox.left) {
          bbox.left = x;
        }

        if (bbox.right === null) {
          bbox.right = x;
        } else if (bbox.right < x) {
          bbox.right = x;
        }

        if (bbox.bottom === null) {
          bbox.bottom = y;
        } else if (bbox.bottom < y) {
          bbox.bottom = y;
        }
      }
    }

    width = bbox.right - bbox.left;
    height = bbox.bottom - bbox.top;
    const trimmed = ctx.getImageData(bbox.left, bbox.top, width, height);

    copy.canvas.width = width;
    copy.canvas.height = height;
    copy.putImageData(trimmed, 0, 0);
  } catch (_err) {
    /* Gotcha! */
  }

  // open new window with trimmed image:
  return {
    canvas: copy?.canvas ?? canvas,
    bbox: {
      ...bbox,
      width,
      height,
    },
  };
};

/**
 * JavaScript clamped arrays will follow the byte ordering of their platform (either little-
 * or big endian).
 * @returns {string} "little endian" if byte ordering starts to the right, or
 * "big endian" if byte ordering starts from the left.
 */
function checkEndian() {
  const arrayBuffer = new ArrayBuffer(2);
  const uint8Array = new Uint8Array(arrayBuffer);
  const uint16array = new Uint16Array(arrayBuffer);

  uint8Array[0] = 0xaa; // set first byte
  uint8Array[1] = 0xbb; // set second byte

  if (uint16array[0] === 0xbbaa) {
    return "little endian";
  }
  if (uint16array[0] === 0xaabb) {
    return "big endian";
  }
  // The most common architectures (x86 and ARM) are both little endian, so just assume that.
  console.error("Can not determine platform endianness, assuming little endian");
  return "little endian";
}

export default {
  Region2RLE,
  RLE2Region,
  mask2DataURL,
  maskDataURL2Image,
  createBrushSizeCircleCursor,
  brushCursorFitsCss,
  isSinglePointPath,
  strokeBrushPath,
  MAX_CSS_CURSOR_SIZE,
  labelToSVG,
  trim,
};

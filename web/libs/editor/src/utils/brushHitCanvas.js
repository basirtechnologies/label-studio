import { colorToRGBAArray } from "./colors";

/** Reuse a bitmap hit map only for the exact image, dimensions and Konva shape color. */
export function brushHitCanvas(cache, image, width, height, colorKey) {
  if (cache?.image === image && cache.width === width && cache.height === height && cache.colorKey === colorKey) {
    return cache;
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(image, 0, 0, width, height);
  const pixels = ctx.getImageData(0, 0, width, height);
  const color = colorToRGBAArray(colorKey);
  for (let i = 0; i < pixels.data.length; i += 4) {
    if (pixels.data[i + 3]) {
      pixels.data[i] = color[0];
      pixels.data[i + 1] = color[1];
      pixels.data[i + 2] = color[2];
    }
  }
  ctx.putImageData(pixels, 0, 0);
  return { image, width, height, colorKey, canvas };
}

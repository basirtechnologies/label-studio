import { decode, encode } from "@thi.ng/rle-pack";
import { LabelStudio } from "@humansignal/frontend-test/helpers/LSF";

const config = `<View><Image name="pages" valueList="$pages"/>
  <BrushLabels name="tag1" toName="pages"><Label value="Object"/></BrushLabels>
  <RectangleLabels name="labels1" toName="pages"><Label value="Box"/></RectangleLabels></View>`;
const svg = (w: number, h: number) =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"/>`)}`;
const data = { pages: [svg(240, 160), svg(320, 220)] };
const result = [0, 1].flatMap((page) =>
  [0, 1, 2].map((object) => {
    const width = page ? 320 : 240;
    const height = page ? 220 : 160;
    const pixels = new Uint8Array(width * height * 4);
    // Each object is a continuous filled area, with several objects on each page.
    for (let y = 20; y < 55; y++)
      for (let x = 10 + object * 65; x < 45 + object * 65; x++)
        pixels.fill(255, (y * width + x) * 4, (y * width + x + 1) * 4);
    return {
      id: `mask-${page}-${object}`,
      item_index: page,
      from_name: "tag1",
      to_name: "pages",
      type: "brushlabels",
      original_width: width,
      original_height: height,
      image_rotation: 0,
      value: { format: "rle", rle: Array.from(encode(pixels, pixels.length)), brushlabels: ["Object"] },
    };
  }),
);
const coverage = (r: any) => Array.from(decode(r.value.rle));
const assertMasksEqual = (actual: any[], expected: any[]) => {
  expect(actual.map((r) => [r.id, r.item_index, r.original_width, r.original_height])).to.deep.equal(
    expected.map((r) => [r.id, r.item_index, r.original_width, r.original_height]),
  );
  actual.forEach((r, index) => {
    const a = coverage(r);
    const b = coverage(expected[index]);
    expect(a.length).to.equal(b.length);
    expect(
      a.every((pixel, i) => pixel === b[i]),
      `every RGBA byte for ${r.id}`,
    ).to.equal(true);
  });
};

describe("DW-895 complete native mask persistence", () => {
  it("retains every decoded pixel across repeated save/load on pages with different dimensions", () => {
    LabelStudio.params().config(config).data(data).withResult(result).init();
    LabelStudio.waitForImageReady();
    LabelStudio.serialize().then((rows) => {
      assertMasksEqual(rows, result);
      LabelStudio.params()
        .config(config)
        .data(data)
        .withResult(JSON.parse(JSON.stringify(rows)))
        .init();
    });
    LabelStudio.waitForImageReady();
    cy.window().then((win) => win.Htx.annotationStore.selected.names.get("pages").setCurrentImage(1));
    LabelStudio.waitForImageReady();
    LabelStudio.serialize().then((rows) => assertMasksEqual(rows, result));
  });
  it("submits current edited pixels rather than the initial snapshot during image loading", () => {
    LabelStudio.params().config(config).data(data).withResult(result).init();
    LabelStudio.waitForImageReady();
    let edited: any[];
    cy.window().then((win) => {
      const ann = win.Htx.annotationStore.selected;
      const image = ann.names.get("pages");
      const region = ann.regionStore.regions.find((r: any) => r.cleanId === "mask-0-0");
      const w = image.stageWidth;
      const h = image.stageHeight;
      region.beginPath({ type: "add", strokeWidth: 25 });
      region.addPoint(w * 0.12, h * 0.27);
      region.addPoint(w * 0.12, h * 0.65);
      region.endPath();
      edited = JSON.parse(JSON.stringify(ann.serializeAnnotation()));
      expect(coverage(edited[0]).filter((v, i) => i % 4 === 3 && v > 0).length).to.be.greaterThan(35 * 35);
      // Controlled reproduction of the confirmed loss mechanism; not claimed as the production trigger.
      image.currentImageEntity.setImageLoaded(false);
      const sent = JSON.parse(JSON.stringify(ann.serializeAnnotation()));
      assertMasksEqual(sent, edited);
      image.currentImageEntity.setImageLoaded(true);
      ann.deleteAllRegions();
      ann.deserializeResults(sent);
    });
    LabelStudio.serialize().then((rows) => assertMasksEqual(rows, edited));
  });
});

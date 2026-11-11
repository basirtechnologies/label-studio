import { brushPointer as pointer } from "../../helpers/brushScene";
import { decode } from "@thi.ng/rle-pack";
import { LabelStudio } from "@humansignal/frontend-test/helpers/LSF";

const config = `<View><Image name="pages" valueList="$pages"/>
  <BrushLabels name="tag1" toName="pages"><Label value="Object" background="red"/></BrushLabels>
  <RectangleLabels name="labels1" toName="pages"><Label value="Box"/></RectangleLabels></View>`;
const svg = (w: number, h: number) =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="white"/></svg>`)}`;
const data = { pages: [svg(400, 300), svg(600, 450)] };

const livePixels = (xs: number[]) => {
  cy.window().should((win) => {
    const ann = win.Htx.annotationStore.selected;
    expect(ann.isDrawing, "pointer is still held, before endPath").to.equal(true);
    expect(ann.regionStore.regions[0].touches, "pending stroke is not committed yet").to.have.length.at.most(1);
    const image = ann.names.get("pages");
    const stage = image.stageRef;
    const canvas = win.document.createElement("canvas");
    canvas.width = stage.width();
    canvas.height = stage.height();
    const ctx = canvas.getContext("2d")!;
    // Read actual rendered scene canvases, not serialization or a forced stage redraw.
    for (const layer of stage.getLayers()) {
      if (layer.visible()) ctx.drawImage(layer.canvas._canvas, 0, 0, canvas.width, canvas.height);
    }
    for (const x of xs) {
      const p = stage.getAbsoluteTransform().point({ x: (image.stageWidth * x) / 400, y: image.stageHeight * 0.4 });
      const rgba = ctx.getImageData(Math.round(p.x), Math.round(p.y), 1, 1).data;
      expect(rgba[0], `red channel at ${x} during held stroke`).to.be.greaterThan(200);
      expect(rgba[1], `paint remains visible at ${x} during held stroke`).to.be.lessThan(200);
    }
  });
};
const selectBrush = () => {
  cy.window().then((win) => {
    const ann = win.Htx.annotationStore.selected;
    if (ann.regionStore.regions.length) ann.selectArea(ann.regionStore.regions[0]);
    else cy.contains(".lsf-label__text", "Object").click();
  });
  cy.get('button[aria-label="brush-tool"]').click();
};

// CDP is used for native held-pointer events, as in the native panel-hover regression.
describe("DW-894 overlapping brush live preview", { browser: { family: "chromium" } }, () => {
  for (const mode of ["submit", "update"] as const) {
    it(`keeps pending pixels across mask entry/exit, then preserves coverage through ${mode} and reopen`, () => {
      const page = mode === "submit" ? 0 : 1;
      let sent: any[] | undefined;
      const capture = (_store: any, ann: any) => {
        sent = JSON.parse(JSON.stringify(ann.serializeAnnotation()));
      };
      LabelStudio.params()
        .config(config)
        .data(data)
        .withAnnotation({ userGenerate: true, result: [] })
        .withEventListener("submitAnnotation", capture)
        .init();
      LabelStudio.waitForImageReady();
      cy.window().then((win) => win.Htx.annotationStore.selected.names.get("pages").setCurrentImage(page));
      LabelStudio.waitForImageReady();
      selectBrush();
      pointer(120, 70);
      pointer(120, 70, "mousePressed", true);
      pointer(120, 170, "mouseMoved", true);
      pointer(120, 170, "mouseReleased");
      cy.window().should((win) => expect(win.Htx.annotationStore.selected.regionStore.regions).to.have.length(1));
      if (mode === "update") {
        LabelStudio.serialize().then((rows) => {
          LabelStudio.params()
            .config(config)
            .data(data)
            .withResult(JSON.parse(JSON.stringify(rows)))
            .withEventListener("updateAnnotation", capture)
            .init();
        });
        LabelStudio.waitForImageReady();
        cy.window().then((win) => win.Htx.annotationStore.selected.names.get("pages").setCurrentImage(page));
        LabelStudio.waitForImageReady();
      }
      selectBrush();
      pointer(40, 120);
      pointer(40, 120, "mousePressed", true);
      pointer(90, 120, "mouseMoved", true);
      livePixels([60]);
      pointer(120, 120, "mouseMoved", true); // Cross existing painted pixels; used to clear the live preview.
      livePixels([60, 90]);
      pointer(180, 120, "mouseMoved", true); // Leave the existing mask while STILL holding the pointer.
      livePixels([60, 90, 150]);
      pointer(180, 120, "mouseReleased");
      cy.window().should((win) => expect(win.Htx.annotationStore.selected.isDrawing).to.equal(false));
      cy.contains("button", mode === "submit" ? "Submit" : "Update").click();
      cy.wrap(null).should(() => expect(sent, `${mode} event payload`).to.have.length(1));
      cy.then(() => {
        const row = sent![0];
        expect(row.item_index).to.equal(page);
        const pixels = decode(row.value.rle);
        for (const [x, y] of [
          [60, 120],
          [90, 120],
          [120, 90],
          [120, 150],
          [150, 120],
        ]) {
          const col = Math.round((row.original_width * x) / 400);
          const line = Math.round((row.original_height * y) / 300);
          expect(pixels[(line * row.original_width + col) * 4 + 3], `saved painted pixel ${x},${y}`).to.be.greaterThan(
            0,
          );
        }
        LabelStudio.params().config(config).data(data).withResult(sent).init();
      });
      LabelStudio.waitForImageReady();
      cy.window().then((win) => win.Htx.annotationStore.selected.names.get("pages").setCurrentImage(page));
      LabelStudio.waitForImageReady();
      LabelStudio.serialize().then((rows) => {
        expect(rows[0].item_index).to.equal(page);
        expect([rows[0].original_width, rows[0].original_height]).to.deep.equal([
          sent![0].original_width,
          sent![0].original_height,
        ]);
        const actual = decode(rows[0].value.rle);
        const expected = decode(sent![0].value.rle);
        expect(actual.length).to.equal(expected.length);
        expect(
          actual.every((v: number, i: number) => v === expected[i]),
          "every saved RGBA byte after reopen",
        ).to.equal(true);
      });
    });
  }
});

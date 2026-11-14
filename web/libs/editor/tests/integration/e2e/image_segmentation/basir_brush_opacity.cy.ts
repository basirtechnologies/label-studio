import { decode } from "@thi.ng/rle-pack";
import { LabelStudio } from "@humansignal/frontend-test/helpers/LSF";
import { brushPointer as pointer, brushScenePixels } from "../../helpers/brushScene";

const config = `<View><Image name="pages" valueList="$pages"/>
  <BrushLabels name="tag1" toName="pages"><Label value="Object" background="red"/></BrushLabels>
  <RectangleLabels name="labels1" toName="pages"><Label value="Box"/></RectangleLabels></View>`;
const svg = (w: number, h: number) =>
  `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="white"/></svg>`,
  )}`;
const data = { pages: [svg(400, 300), svg(600, 450)] };
const samples = [
  [80, 100],
  [110, 100],
  [110, 80],
]; // Old-only, overlap, new-only; away from AA edges/cursor.
const assertCoverage = (actual: any[], expected: any[]) => {
  expect(actual.map((r) => [r.id, r.item_index, r.original_width, r.original_height])).to.deep.equal(
    expected.map((r) => [r.id, r.item_index, r.original_width, r.original_height]),
  );
  actual.forEach((row, n) => {
    const a = decode(row.value.rle);
    const b = decode(expected[n].value.rle);
    expect(a.length).to.equal(b.length);
    expect(
      a.every((v: number, i: number) => v === b[i]),
      `every coverage byte in mask ${n}`,
    ).to.equal(true);
  });
};
const alpha = (row: any, x: number, y: number) => {
  const px = Math.round((row.original_width * x) / 400);
  const py = Math.round((row.original_height * y) / 300);
  return decode(row.value.rle)[(py * row.original_width + px) * 4 + 3];
};

describe("Uniform same-mask brush opacity", { browser: { family: "chromium" } }, () => {
  for (const mode of ["continuous", "restart", "separate"] as const) {
    it(`preserves colors and coverage during ${mode} painting, release, submission and reopening`, () => {
      const page = mode === "restart" ? 1 : 0;
      const count = mode === "separate" ? 2 : 1;
      const greens = [102, mode === "separate" ? 41 : 102, 102]; // 60% red once per mask, never once per stroke.
      let sent: any[] | undefined;
      const capture = (_store: any, ann: any) => {
        sent = JSON.parse(JSON.stringify(ann.serializeAnnotation()));
      };
      const init = (rows?: any[]) => {
        const builder = LabelStudio.params()
          .config(config)
          .data(data)
          .withEventListener("submitAnnotation", capture)
          .withEventListener("updateAnnotation", capture);
        if (rows) builder.withResult(rows);
        else builder.withAnnotation({ userGenerate: true, result: [] });
        builder.init();
        LabelStudio.waitForImageReady();
        cy.window().then((win) => win.Htx.annotationStore.selected.names.get("pages").setCurrentImage(page));
        LabelStudio.waitForImageReady();
      };
      const brush = () => {
        cy.get('button[aria-label="brush-tool"]').click();
        cy.window().then((win) =>
          win.Htx.annotationStore.selected.names.get("pages").getToolsManager().findSelectedTool().setStroke(60),
        );
      };
      const colors = (expected: number[], held: boolean) => {
        cy.window().should((win) => {
          const ann = win.Htx.annotationStore.selected;
          const image = ann.names.get("pages");
          expect(image.getToolsManager().findSelectedTool()?.mode === "drawing", "active native stroke").to.equal(held);
          const masks = [...ann.regionStore.regions, ...(image.drawingRegion ? [image.drawingRegion] : [])];
          expect(masks).to.have.length(count);
          expect(
            masks.every((r: any) => !r.highlighted),
            "hover is not changing the color",
          ).to.equal(true);
          brushScenePixels(win, samples).forEach((rgba, n) => {
            [255, expected[n], expected[n], 255].forEach((v, channel) => {
              expect(rgba[channel], `sample ${n}, channel ${channel}, held=${held}`).to.be.closeTo(v, 3);
            });
          });
        });
      };
      const roundtrip = (button: string, expected: number[]) => {
        let before: any[];
        cy.window().then((win) => {
          before = JSON.parse(JSON.stringify(win.Htx.annotationStore.selected.serializeAnnotation()));
          sent = undefined;
        });
        cy.contains("button", button).click();
        cy.wrap(null).should(() => expect(sent).to.have.length(count));
        cy.then(() => {
          assertCoverage(sent!, before);
          init(sent);
        });
        LabelStudio.serialize().then((rows) => assertCoverage(rows, before));
        colors(expected, false);
      };
      init();
      cy.contains(".lsf-label__text", "Object").click();
      brush();
      pointer(60, 100);
      pointer(60, 100, "mousePressed", true);
      pointer(180, 100, "mouseMoved", true);
      if (mode === "continuous") {
        pointer(180, 60, "mouseMoved", true);
        pointer(110, 60, "mouseMoved", true);
      } else {
        pointer(180, 100, "mouseReleased");
        cy.window().should((win) => expect(win.Htx.annotationStore.selected.regionStore.regions).to.have.length(1));
        if (mode === "restart") {
          LabelStudio.serialize().then((rows) => init(JSON.parse(JSON.stringify(rows))));
          cy.window().then((win) => {
            const ann = win.Htx.annotationStore.selected;
            ann.selectArea(ann.regionStore.regions[0]);
            expect(ann.regionStore.regions[0].rle.length).to.be.greaterThan(0);
            const image = ann.names.get("pages");
            image.setZoom(image.currentZoom * 1.2);
            image.setZoomPosition(-20, -10);
          });
        } else {
          cy.window().then((win) => win.Htx.annotationStore.selected.unselectAll());
          cy.contains(".lsf-label__text", "Object").click();
        }
        brush();
        pointer(110, 60);
        pointer(110, 60, "mousePressed", true);
      }
      pointer(110, 180, "mouseMoved", true);
      colors(greens, true); // Real scene pixels before mouse-up, not just final-mask existence.
      pointer(110, 180, "mouseReleased");
      colors(greens, false);
      LabelStudio.serialize().then((rows) => {
        expect(alpha(rows[0], 80, 100)).to.be.greaterThan(0);
        expect(alpha(rows[count - 1], 110, 80)).to.be.greaterThan(0);
        rows.forEach((row) => expect(alpha(row, 110, 100)).to.be.greaterThan(0));
      });
      roundtrip(mode === "restart" ? "Update" : "Submit", greens);
      if (mode === "separate") {
        let bottom: any;
        LabelStudio.serialize().then((rows) => {
          bottom = rows[0];
        });
        cy.window().then((win) => {
          const ann = win.Htx.annotationStore.selected;
          ann.selectArea(ann.regionStore.regions[1]);
        });
        cy.get('button[aria-label="eraser"]').click();
        cy.window().then((win) =>
          win.Htx.annotationStore.selected.names.get("pages").getToolsManager().findSelectedTool().setStroke(60),
        );
        pointer(110, 60);
        pointer(110, 60, "mousePressed", true);
        pointer(110, 140, "mouseMoved", true);
        colors([102, 102, 255], true); // Erasing the selected mask must reveal, rather than erase, the other mask.
        pointer(110, 140, "mouseReleased");
        colors([102, 102, 255], false);
        LabelStudio.serialize().then((rows) => {
          assertCoverage([rows[0]], [bottom]);
          expect(alpha(rows[1], 110, 100)).to.equal(0);
        });
        roundtrip("Update", [102, 102, 255]);
      }
    });
  }
});

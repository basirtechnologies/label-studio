import { ImageView, LabelStudio } from "@humansignal/frontend-test/helpers/LSF";

const config = `<View>
  <Image name="pages" valueList="$pages"/>
  <BrushLabels name="tag1" toName="pages"><Label value="Mask"/></BrushLabels>
  <RectangleLabels name="labels1" toName="pages"><Label value="Box"/></RectangleLabels>
</View>`;
const svg = (w: number, h: number) =>
  `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="white"/></svg>`,
  )}`;
const data = { pages: [svg(240, 160), svg(320, 200)] };
const boxes = [1, 0].map((index) => ({
  id: `box-page-${index}`,
  from_name: "labels1",
  to_name: "pages",
  type: "rectanglelabels",
  item_index: index,
  original_width: index ? 320 : 240,
  original_height: index ? 200 : 160,
  image_rotation: 0,
  value: { x: 10, y: 10, width: 20, height: 20, rotation: 0, rectanglelabels: ["Box"] },
}));

describe("DW-892 Regions grouped by saved image page", () => {
  it("groups by item_index, navigates on selection, and retains pages after reopening", () => {
    LabelStudio.params().config(config).data(data).withResult(boxes).init();
    LabelStudio.waitForImageReady();
    cy.contains("Page 1").should("be.visible");
    cy.contains("Page 2").should("be.visible");
    cy.window().then((win) => {
      const ann = win.Htx.annotationStore.selected;
      const region = [...ann.areas.values()].find((r: any) => r.item_index === 1);
      // Exercise the same selection action that region rows use.
      ann.selectArea(region);
      expect(ann.names.get("pages").currentImage).to.equal(1);
    });
    ImageView.waitForImage();
    LabelStudio.serialize().then((result) => {
      expect(result.map((r: any) => r.item_index).sort()).to.deep.equal([0, 1]);
      LabelStudio.params().config(config).data(data).withResult(result).init();
    });
    LabelStudio.waitForImageReady();
    cy.contains("Page 1").should("be.visible");
    cy.contains("Page 2").should("be.visible");
    LabelStudio.serialize().then((result) => {
      expect(result.map((r: any) => [r.id, r.item_index]).sort()).to.deep.equal(
        boxes.map((r) => [r.id, r.item_index]).sort(),
      );
    });
  });
});

import { LabelStudio } from "@humansignal/frontend-test/helpers/LSF";

const config = `<View><Image name="pages" valueList="$pages"/>
  <RectangleLabels name="labels1" toName="pages"><Label value="Box" hotkey="r"/></RectangleLabels></View>`;
const image = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="80"/%3E';
const result = [0, 1].map((page) => ({
  id: `box-${page}`,
  from_name: "labels1",
  to_name: "pages",
  type: "rectanglelabels",
  item_index: page,
  original_width: 100,
  original_height: 80,
  image_rotation: 0,
  value: { x: 10, y: 10, width: 20, height: 20, rotation: 0, rectanglelabels: ["Box"] },
}));

describe("DW-896 visibility shortcut", () => {
  it("toggles all pages like the eye, ignores held keys/text entry, and never changes geometry", () => {
    LabelStudio.params()
      .config(config)
      .data({ pages: [image, image] })
      .withResult(result)
      .init();
    LabelStudio.waitForImageReady();
    let before: string;
    LabelStudio.serialize().then((r) => {
      before = JSON.stringify(r);
    });
    cy.window().then((win) => {
      const regions = win.Htx.annotationStore.selected.regionStore.regions;
      regions[0].toggleHidden(); // mixed state: the shared action hides all first
      win.document.body.dispatchEvent(
        new win.KeyboardEvent("keydown", { bubbles: true, key: "H", keyCode: 72, ctrlKey: true, shiftKey: true }),
      );
      expect(regions.every((r: any) => r.hidden)).to.equal(true);
      win.document.body.dispatchEvent(
        new win.KeyboardEvent("keydown", {
          bubbles: true,
          key: "H",
          keyCode: 72,
          ctrlKey: true,
          shiftKey: true,
          repeat: true,
        }),
      );
      expect(regions.every((r: any) => r.hidden)).to.equal(true);
    });
    cy.get('button[aria-label="Show all regions"]').click();
    cy.window().then((win) => {
      const ann = win.Htx.annotationStore.selected;
      expect(ann.regionStore.regions.every((r: any) => !r.hidden)).to.equal(true);
      const input = win.document.createElement("textarea");
      win.document.body.appendChild(input);
      input.focus();
      input.dispatchEvent(
        new win.KeyboardEvent("keydown", { bubbles: true, key: "H", keyCode: 72, ctrlKey: true, shiftKey: true }),
      );
      expect(ann.regionStore.regions.every((r: any) => !r.hidden)).to.equal(true);
      input.remove();
    });
    LabelStudio.serialize().then((r) => expect(JSON.stringify(r)).to.equal(before));
  });
});

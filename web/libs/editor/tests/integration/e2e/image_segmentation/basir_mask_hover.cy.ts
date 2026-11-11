import { encode } from "@thi.ng/rle-pack";
import { LabelStudio } from "@humansignal/frontend-test/helpers/LSF";

const config = `<View><Image name="pages" valueList="$pages"/>
  <BrushLabels name="tag1" toName="pages"><Label value="Object" background="red"/></BrushLabels></View>`;
const image = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="240" height="160"/%3E';
const result = [0, 1].flatMap((page) =>
  [0, 1].map((object) => {
    const rgba = new Uint8Array(240 * 160 * 4);
    for (let y = 30; y < 65; y++)
      for (let x = 20 + object * 110; x < 60 + object * 110; x++)
        rgba.fill(255, (y * 240 + x) * 4, (y * 240 + x + 1) * 4);
    return {
      id: `mask-${page}-${object}`,
      from_name: "tag1",
      to_name: "pages",
      type: "brushlabels",
      item_index: page,
      original_width: 240,
      original_height: 160,
      image_rotation: 0,
      value: { brushlabels: ["Object"], format: "rle", rle: Array.from(encode(rgba, rgba.length)) },
    };
  }),
);
const pointerAt = (x: number, y: number) =>
  cy.window().then((win) => {
    const image = win.Htx.annotationStore.selected.names.get("pages");
    const pos = image.stageRef.getAbsoluteTransform().point({ x: image.stageWidth * x, y: image.stageHeight * y });
    return cy.get(".konvajs-content").trigger("mousemove", pos.x, pos.y, { force: true });
  });
const highlighted = (page: number, object: number) =>
  cy.window().should((win) => {
    const regions = win.Htx.annotationStore.selected.regionStore.regions.filter((r: any) => r.highlighted);
    expect(regions.map((r: any) => r.cleanId)).to.deep.equal([`mask-${page}-${object}`]);
  });

describe("DW-894 active-page mask hover", () => {
  it("highlights only the hit mask, clears page/panel/task hover, and works after zoom and pan", () => {
    LabelStudio.params()
      .config(config)
      .data({ pages: [image, image] })
      .withResult(result)
      .init();
    LabelStudio.waitForImageReady();
    cy.get('button[aria-label="move-tool"]').click();
    pointerAt(40 / 240, 45 / 160);
    highlighted(0, 0);
    pointerAt(150 / 240, 45 / 160);
    highlighted(0, 1);
    pointerAt(0.9, 0.9);
    cy.window().should((win) =>
      expect(win.Htx.annotationStore.selected.regionStore.regions.some((r: any) => r.highlighted)).to.equal(false),
    );
    // Confirmed baseline defect: panel-hovered mask remained highlighted after changing pages.
    cy.get(".lsf-outliner-item__title").first().trigger("mouseenter");
    cy.wait(75);
    cy.window().then((win) => win.Htx.annotationStore.selected.names.get("pages").setCurrentImage(1));
    LabelStudio.waitForImageReady();
    cy.window().should((win) =>
      expect(win.Htx.annotationStore.selected.regionStore.regions.some((r: any) => r.highlighted)).to.equal(false),
    );
    cy.window().should((win) => {
      const active = win.Htx.annotationStore.selected.names.get("pages");
      expect(active.regs.every((r: any) => r._isReady && r.shapeRef)).to.equal(true);
    });
    pointerAt(0.9, 0.9);
    cy.window().should((win) => {
      const image = win.Htx.annotationStore.selected.names.get("pages");
      const pos = image.stageRef
        .getAbsoluteTransform()
        .point({ x: (image.stageWidth * 40) / 240, y: (image.stageHeight * 45) / 160 });
      expect(image.stageRef.getIntersection(pos)?.getParent()?.getParent()?.id()).to.equal("mask-1-0");
    });
    pointerAt(40 / 240, 45 / 160);
    highlighted(1, 0);
    cy.window().then((win) => {
      const image = win.Htx.annotationStore.selected.names.get("pages");
      image.setZoom(image.currentZoom * 1.2);
      image.setZoomPosition(-30, -20);
    });
    cy.window().should((win) => {
      const image = win.Htx.annotationStore.selected.names.get("pages");
      const pos = image.stageRef
        .getAbsoluteTransform()
        .point({ x: (image.stageWidth * 150) / 240, y: (image.stageHeight * 45) / 160 });
      expect(image.stageRef.getIntersection(pos)?.getParent()?.getParent()?.id()).to.equal("mask-1-1");
    });
    pointerAt(150 / 240, 45 / 160);
    highlighted(1, 1);
    LabelStudio.params()
      .config(config)
      .data({ pages: [image, image] })
      .withResult([])
      .init();
    LabelStudio.waitForImageReady();
    cy.window().should((win) => expect(win.Htx.annotationStore.selected.regionStore.regions).to.have.length(0));
  });
});

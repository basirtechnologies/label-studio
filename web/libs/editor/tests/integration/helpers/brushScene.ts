// Native events exercise Konva hit testing and React hover during a real held stroke.
export const brushPointer = (x: number, y: number, type = "mouseMoved", held = false) => {
  cy.window().then((win) => {
    const image = win.Htx.annotationStore.selected.names.get("pages");
    const point = image.stageRef.getAbsoluteTransform().point({
      x: (image.stageWidth * x) / 400,
      y: (image.stageHeight * y) / 300,
    });
    const rect = image.stageRef.content.getBoundingClientRect();
    const frame = window.top!.document.querySelector("iframe.aut-iframe")!.getBoundingClientRect();
    const scale = frame.width / win.innerWidth;
    return Cypress.automation("remote:debugger:protocol", {
      command: "Input.dispatchMouseEvent",
      params: {
        type,
        x: frame.left + (rect.left + point.x) * scale,
        y: frame.top + (rect.top + point.y) * scale,
        button: type === "mouseMoved" ? "none" : "left",
        buttons: held ? 1 : 0,
        clickCount: type === "mouseMoved" ? 0 : 1,
      },
    });
  });
  // Let React effects and Konva's scheduled redraw run BEFORE examining live pixels.
  cy.window().then(
    (win) => new Promise((resolve) => win.requestAnimationFrame(() => win.requestAnimationFrame(resolve))),
  );
};

export const brushScenePixels = (win: any, points: number[][]) => {
  const image = win.Htx.annotationStore.selected.names.get("pages");
  const stage = image.stageRef;
  const canvas = win.document.createElement("canvas");
  canvas.width = stage.width();
  canvas.height = stage.height();
  const ctx = canvas.getContext("2d")!;
  for (const layer of stage.getLayers()) {
    if (layer.visible()) ctx.drawImage(layer.canvas._canvas, 0, 0, canvas.width, canvas.height);
  }
  return points.map(([x, y]) => {
    const p = stage.getAbsoluteTransform().point({ x: (image.stageWidth * x) / 400, y: (image.stageHeight * y) / 300 });
    return Array.from(ctx.getImageData(Math.round(p.x), Math.round(p.y), 1, 1).data) as number[];
  });
};

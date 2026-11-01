/**
 * Basir DW-891: picking a brush label while the eraser is active goes back to the brush.
 * Label#onLabelInteract only switches tools for the first selected label of a group, and the brush
 * has no default hotkey, so without this the label key would leave the eraser active.
 *
 * @param {Record<string, object>} controlTools tools of the label's control (e.g. BrushLabels: brush, eraser)
 * @param {object | undefined} selectedTool the active tool of the object
 * @returns {object | null} the brush to select, or null to keep the current tool
 */
export const brushToSelectOnLabelPick = (controlTools, selectedTool) => {
  if (!selectedTool || selectedTool.toolName !== "EraserTool") return null;

  const brush = Object.values(controlTools || {}).find((tool) => tool?.toolName === "BrushTool");

  return brush && brush !== selectedTool ? brush : null;
};

import { describe, expect, test } from "bun:test";
import { ANNOTATION_REDISTRIBUTED, operationErrorDetail, redistributedAnnotationDetail } from "./operation-error-toast";

const DETAIL = "This rejected annotation was passed to another annotator and can no longer be updated.";

describe("redistributedAnnotationDetail", () => {
  test("returns the 403 detail when display_context marks a redistributed annotation", () => {
    expect(
      redistributedAnnotationDetail(403, {
        detail: DETAIL,
        display_context: { reason: ANNOTATION_REDISTRIBUTED },
      }),
    ).toBe(DETAIL);
  });

  test("ignores a generic 403 so retry/support copy stays in place", () => {
    expect(redistributedAnnotationDetail(403, { detail: "Permission denied" })).toBeNull();
  });

  test("ignores pause 403s that have a different display_context reason", () => {
    expect(
      redistributedAnnotationDetail(403, {
        detail: "You are paused in this project.",
        display_context: { reason: "PAUSED" },
      }),
    ).toBeNull();
  });

  test("ignores server errors that should still ask the user to retry", () => {
    expect(redistributedAnnotationDetail(500, { detail: "Internal server error" })).toBeNull();
  });

  test("ignores empty or non-string 403 payloads", () => {
    expect(
      redistributedAnnotationDetail(403, {
        detail: "   ",
        display_context: { reason: ANNOTATION_REDISTRIBUTED },
      }),
    ).toBeNull();
    expect(
      redistributedAnnotationDetail(403, {
        detail: { nested: true },
        display_context: { reason: ANNOTATION_REDISTRIBUTED },
      }),
    ).toBeNull();
    expect(redistributedAnnotationDetail(undefined, { detail: DETAIL })).toBeNull();
  });
});

describe("operationErrorDetail", () => {
  test("returns the detail of a webhook rejection (400)", () => {
    expect(operationErrorDetail(400, { detail: "wrong object" })).toBe("wrong object");
  });

  test("trims the detail and accepts other client errors", () => {
    expect(operationErrorDetail(403, { detail: "  You do not have permission  " })).toBe("You do not have permission");
  });

  test("falls back to the generic copy for server errors", () => {
    expect(operationErrorDetail(500, { detail: "Internal server error" })).toBeNull();
    expect(operationErrorDetail(undefined, { detail: "wrong object" })).toBeNull();
  });

  test("falls back for empty, missing, non-string and placeholder details", () => {
    expect(operationErrorDetail(400, { detail: "   " })).toBeNull();
    expect(operationErrorDetail(400, {})).toBeNull();
    expect(operationErrorDetail(400, null)).toBeNull();
    expect(operationErrorDetail(400, { detail: { message: "x" } })).toBeNull();
    expect(operationErrorDetail(400, { detail: "Validation error" })).toBeNull();
    expect(operationErrorDetail(400, { detail: "Unknown error" })).toBeNull();
  });
});

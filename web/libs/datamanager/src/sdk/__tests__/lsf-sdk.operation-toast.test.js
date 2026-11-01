import { beforeEach, describe, expect, it, mock } from "bun:test";
import { LSFWrapper } from "../lsf-sdk";

// Basir: a webhook rejection comes back as HTTP 400 with detail = the Label Server's message.
// onSubmitAnnotation, onUpdateAnnotation and onSkipTask all hand their API result to showOperationToast.
const rejection = (detail = "wrong object") => ({ $meta: { status: 400 }, response: { detail } });

const toastCalls = (invoke) => invoke.mock.calls.filter(([event]) => event === "toast").map(([, payload]) => payload);

describe("LSFWrapper operation toast shows the server detail", () => {
  let wrapper;

  beforeEach(() => {
    wrapper = Object.create(LSFWrapper.prototype);
    wrapper.datamanager = { invoke: mock(() => {}) };
  });

  it.each([
    ["Annotation is not saved"], // submit
    ["Annotation is not updated"], // update
    ["Task is not skipped"], // skip
  ])("%s: toast text includes the detail", (errorAction) => {
    wrapper.showOperationToast(400, "ok", errorAction, rejection());

    expect(toastCalls(wrapper.datamanager.invoke)).toEqual([
      { message: `${errorAction}: wrong object`, type: "error" },
    ]);
  });

  it("keeps the generic retry/support toast when there is no detail", () => {
    wrapper.showOperationToast(500, "ok", "Annotation is not updated", { $meta: { status: 500 }, response: {} });

    const [toast] = toastCalls(wrapper.datamanager.invoke);
    expect(toast.type).toBe("error");
    expect(typeof toast.message).not.toBe("string"); // the JSX fallback with the support link
  });
});

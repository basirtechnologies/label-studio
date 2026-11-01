/**
 * Classic Data Manager toasts a generic "not updated, try again / contact support"
 * for every failed annotation write. Expected 403s tagged with display_context
 * (for example a redistributed rejection) already explain themselves in `detail`
 * and should not ask the annotator to retry.
 */
export const ANNOTATION_REDISTRIBUTED = "ANNOTATION_REDISTRIBUTED";

type ErrorResponse = {
  detail?: unknown;
  display_context?: { reason?: unknown };
};

export const redistributedAnnotationDetail = (
  status: number | undefined,
  response: ErrorResponse | null | undefined,
): string | null => {
  if (status !== 403 || response?.display_context?.reason !== ANNOTATION_REDISTRIBUTED) {
    return null;
  }
  const detail = response.detail;
  if (typeof detail !== "string") return null;
  const trimmed = detail.trim();
  return trimmed ? trimmed : null;
};

/**
 * Placeholders the API's exception handler (core.utils.common.custom_exception_handler) puts in `detail`
 * when it has nothing specific to say; the generic retry/support copy is more useful than these.
 */
const PLACEHOLDER_DETAILS = new Set(["Unknown error", "Validation error"]);

/**
 * Basir: a failed annotation write (submit, update, skip) whose 4xx response carries a readable `detail`
 * shows that text, e.g. our Label Server's webhook rejection ("wrong object", HTTP 400). The generic
 * "please try again or contact our team" toast stays the fallback, including for 5xx server errors.
 */
export const operationErrorDetail = (
  status: number | undefined,
  response: ErrorResponse | null | undefined,
): string | null => {
  if (status === undefined || status < 400 || status >= 500) return null;
  const detail = response?.detail;
  if (typeof detail !== "string") return null;
  const trimmed = detail.trim();
  if (!trimmed || PLACEHOLDER_DETAILS.has(trimmed)) return null;
  return trimmed;
};

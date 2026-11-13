/**
 * The AI disclaimer (docs/decisions.md D2, CLAUDE.md section 7). It is a constant of THIS app on purpose: safety text is
 * never taken from a server string. A test asserts it equals ai-svc's `disclaimer` in the recorded example, so the two
 * cannot drift apart unnoticed.
 */
export const AI_DISCLAIMER =
  'AI-generated summary for clinician review only. It may be incomplete or inaccurate. It is not a diagnosis or treatment recommendation. Verify against the patient record.';

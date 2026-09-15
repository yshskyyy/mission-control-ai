export type SubmissionDraft = {
  value: string;
  pending: boolean;
};

export function beginSubmission(state: SubmissionDraft): {
  sent: string;
  next: SubmissionDraft;
} | null {
  const sent = state.value.trim();
  if (state.pending || !sent) return null;
  return { sent, next: { value: "", pending: true } };
}

export function finishSubmission(currentValue = ""): SubmissionDraft {
  return { value: currentValue, pending: false };
}

export function failSubmission(currentValue: string, sent: string): SubmissionDraft {
  return { value: currentValue === "" ? sent : currentValue, pending: false };
}

export function shouldSubmitOnEnter(
  event: { key: string; shiftKey: boolean; isComposing: boolean },
  pending: boolean,
  value: string,
): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.isComposing && !pending && !!value.trim();
}

import assert from "node:assert/strict";
import test from "node:test";

import {
  beginSubmission,
  failSubmission,
  finishSubmission,
  shouldSubmitOnEnter,
} from "../src/submissionState.ts";

test("begin trims, clears immediately, and locks duplicate submission", () => {
  assert.deepEqual(beginSubmission({ value: "  第一个问题  ", pending: false }), {
    sent: "第一个问题",
    next: { value: "", pending: true },
  });
  assert.equal(beginSubmission({ value: "第二个问题", pending: true }), null);
  assert.equal(beginSubmission({ value: "  \n ", pending: false }), null);
});

test("keyboard submission respects shift, composition, blank content, and pending", () => {
  const enter = { key: "Enter", shiftKey: false, isComposing: false };
  assert.equal(shouldSubmitOnEnter(enter, false, "问题"), true);
  assert.equal(shouldSubmitOnEnter({ ...enter, shiftKey: true }, false, "问题"), false);
  assert.equal(shouldSubmitOnEnter({ ...enter, isComposing: true }, false, "问题"), false);
  assert.equal(shouldSubmitOnEnter(enter, true, "问题"), false);
  assert.equal(shouldSubmitOnEnter(enter, false, "  \n"), false);
});

test("success remains empty", () => {
  assert.deepEqual(finishSubmission(), { value: "", pending: false });
  assert.deepEqual(finishSubmission("下一条问题"), { value: "下一条问题", pending: false });
});

test("failure restores only when no newer input exists", () => {
  assert.deepEqual(failSubmission("", "失败的问题"), {
    value: "失败的问题",
    pending: false,
  });
  assert.deepEqual(failSubmission("等待期间的新问题", "失败的问题"), {
    value: "等待期间的新问题",
    pending: false,
  });
});

import test from "node:test";
import assert from "node:assert/strict";
import {
  buildMap,
  toOutput,
  toSource,
  inverse,
  derive,
  replaceCue,
  splitCue,
  mergeCue,
  chooseCorrection,
  History,
  makeRequest,
} from "../../ui/frontend/editor_model.mjs";
let count = 0;
const id = () => `test-${++count}`;
const caption = (name, start, text) => ({
  id: name,
  spans: [{ start, end: start + 4 }],
  text,
  highlights: [],
  atoms: [],
  manual: true,
  review_reason: "",
});
const state = () => ({
  duration: 15,
  sources: [
    caption("a", 0, "先確認需求"),
    caption("b", 5, "講錯重講"),
    caption("c", 10, "再確認預算"),
  ],
  cuts: [],
  corrections: [],
  style: { preset: "basic", font_size: 52, bottom_percent: 12 },
  enabled: true,
});
test("cut mapping, skip region and inverse are deterministic", () => {
  const map = buildMap(15, [
    { start: 5, end: 10, selected: true, confirmed: true },
  ]);
  assert.equal(map.at(-1).output_end, 10);
  assert.equal(toOutput(12, map), 7);
  assert.equal(toSource(7, map), 12);
  assert.deepEqual(inverse(4, 6, map), [
    { start: 4, end: 5 },
    { start: 10, end: 11 },
  ]);
});
test("unconfirmed, reversed and all-video cuts rejected", () => {
  for (const cut of [
    { start: 1, end: 3, selected: true, confirmed: false },
    { start: 4, end: 3, selected: true, confirmed: true },
    { start: 0, end: 15, selected: true, confirmed: true },
  ])
    assert.throws(() => buildMap(15, [cut]));
});
test("retake captions disappear and later subtitles shift then restore", () => {
  const s = state();
  s.cuts = [{ start: 5, end: 10, selected: true, confirmed: true }];
  let d = derive(s);
  assert.equal(d.cues.length, 2);
  assert.equal(d.cues[1].start, 5);
  s.cuts[0].selected = false;
  d = derive(s);
  assert.equal(d.cues.length, 3);
  assert.equal(d.cues[2].start, 10);
});
test("text edit keeps anchors, supports split and merge", () => {
  let s = state();
  let r = replaceCue(s, "a", { text: "先確認生活需求" }, id);
  s = r.state;
  assert.equal(derive(s).cues[0].text, "先確認生活需求");
  assert.deepEqual(s.sources[0].spans, [{ start: 0, end: 4 }]);
  r = splitCue(s, r.id, 2, 3, id);
  s = r.state;
  assert.equal(derive(s).cues.length, 4);
  r = mergeCue(s, r.id, id);
  assert.equal(derive(r.state).cues.length, 3);
});
test("manual caption overlapping changed cut needs review", () => {
  const s = state();
  s.cuts = [{ start: 1, end: 2, selected: true, confirmed: true }];
  assert.equal(derive(s).cues[0].needs_review, true);
});
test("history covers text, style and cuts with undo and redo", () => {
  const s = state(),
    history = new History(s),
    changed = state();
  changed.style.font_size = 64;
  history.commit(changed, "style", 1000);
  assert.equal(history.state.style.font_size, 64);
  history.undo();
  assert.equal(history.state.style.font_size, 52);
  history.redo();
  assert.equal(history.state.style.font_size, 64);
});
test("request contains only structured edits, no media or commands", () => {
  const s = state(),
    payload = makeRequest(
      { base_revision: 2, source_sha256: "0".repeat(64) },
      s,
      "11111111-1111-1111-1111-111111111111",
    );
  assert.equal(payload.base_revision, 2);
  assert.equal(payload.captions[0].text, "先確認需求");
  assert.equal(JSON.stringify(payload).includes("media_url"), false);
  assert.equal("atoms" in payload.captions[0], false);
});
test("manual text has priority over script correction", () => {
  const s = state();
  s.corrections = [{ id: "correction", cue_id: "a", decision: "pending" }];
  assert.throws(
    () => chooseCorrection(s, "correction", "accepted", {}),
    /人工/,
  );
});
test("acoustic words inside deleted regions do not reappear", () => {
  const s = state();
  s.sources = [
    {
      id: "word",
      spans: [{ start: 0, end: 4 }],
      text: "一二三四",
      manual: false,
      atoms: [..."一二三四"].map((text, i) => ({
        start: i,
        end: i + 0.9,
        text,
      })),
    },
  ];
  s.duration = 4;
  s.cuts = [{ start: 1, end: 3, selected: true, confirmed: true }];
  assert.equal(
    derive(s)
      .cues.map((c) => c.text)
      .join(""),
    "一四",
  );
});

test("explicit listening confirmation resolves review after changed cut", () => {
  const s = state();
  s.cuts = [{ start: 1, end: 2, selected: true, confirmed: true }];
  const r = replaceCue(s, "a", {}, id);
  assert.equal(derive(r.state).cues[0].needs_review, false);
});

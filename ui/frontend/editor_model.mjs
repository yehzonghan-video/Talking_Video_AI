// Pure editing model: no DOM, network, media bytes, Python, or FFmpeg commands.
export const copy = (value) => JSON.parse(JSON.stringify(value));
export const newId = () => crypto.randomUUID();
// Streamlit supplies /media URLs; preserve the embedding proxy's directory.
// An already prefixed URL must not receive that directory a second time.
export const mediaUrl = (reference, location) =>
  new URL(reference.replace(/^\/media\//, "media/"), location).href;
const finite = (n) => typeof n === "number" && Number.isFinite(n);
export function buildMap(duration, cuts) {
  const ranges = cuts
    .filter((c) => c.selected)
    .map((c) => {
      if (
        !finite(c.start) ||
        !finite(c.end) ||
        c.start < 0 ||
        c.end <= c.start ||
        c.end > duration ||
        !c.confirmed
      )
        throw Error("請確認刪除片段的時間與人工確認狀態。");
      return { start: c.start, end: c.end };
    })
    .sort((a, b) => a.start - b.start);
  const merged = [];
  for (const cut of ranges) {
    const last = merged.at(-1);
    if (last && cut.start <= last.end) last.end = Math.max(last.end, cut.end);
    else merged.push({ ...cut });
  }
  const map = [];
  let source = 0,
    output = 0;
  for (const cut of [...merged, { start: duration, end: duration }]) {
    if (cut.start > source) {
      const length = cut.start - source;
      map.push({
        source_start: source,
        source_end: cut.start,
        output_start: output,
        output_end: output + length,
      });
      output += length;
    }
    source = Math.max(source, cut.end);
  }
  if (output < 0.1) throw Error("不能刪除全部影片。");
  return map;
}
export function toSource(time, map) {
  const p =
    map.find((m) => time >= m.output_start && time < m.output_end) ||
    map.at(-1);
  return Math.min(
    p.source_end,
    p.source_start + Math.max(0, time - p.output_start),
  );
}
export function toOutput(time, map) {
  for (const p of map) {
    if (time < p.source_start) return p.output_start;
    if (time <= p.source_end) return p.output_start + time - p.source_start;
  }
  return map.at(-1).output_end;
}
export function inverse(start, end, map) {
  if (
    !finite(start) ||
    !finite(end) ||
    start < 0 ||
    end <= start ||
    end > map.at(-1).output_end + 0.00001
  )
    throw Error("字幕時間超出剪輯後影片或結束早於開始。");
  return map
    .filter(
      (p) =>
        Math.min(end, p.output_end) - Math.max(start, p.output_start) > 0.00001,
    )
    .map((p) => ({
      start: p.source_start + Math.max(0, start - p.output_start),
      end: p.source_start + Math.min(end, p.output_end) - p.output_start,
    }));
}
export function textWidth(text) {
  return Array.from(text).reduce(
    (n, c) => n + (c === "\n" ? 0 : c.codePointAt(0) >= 0x2e80 ? 1 : 0.5),
    0,
  );
}
export function wrapPreview(text) {
  // Saved layouts use Python's authoritative linguistic hints. For an unsaved
  // cut use browser word segmentation, retaining all characters and punctuation.
  const units =
    typeof Intl.Segmenter === "function"
      ? [
          ...new Intl.Segmenter("zh-Hant", { granularity: "word" }).segment(
            text,
          ),
        ].map((s) => s.segment)
      : Array.from(text);
  let line = "",
    lines = [];
  for (const token of units) {
    if (
      line &&
      textWidth(line + token) > 12 &&
      !/^[，。！？；：、,.!?;:]+$/.test(token)
    ) {
      lines.push(line.trim());
      line = "";
    }
    line += token;
  }
  if (line.trim()) lines.push(line.trim());
  return lines.join("\n");
}
export function mapSources(sources, map, hints = []) {
  const out = [];
  for (const cue of sources) {
    if (cue.atoms?.length && !cue.manual) {
      map.forEach((p, k) => {
        const words = cue.atoms.filter(
          (a) =>
            a.start >= p.source_start - 0.00001 &&
            a.end <= p.source_end + 0.00001,
        );
        const partial = cue.atoms.filter(
          (a) =>
            Math.min(a.end, p.source_end) > Math.max(a.start, p.source_start) &&
            !words.includes(a),
        );
        if (words.length) {
          const spans = [{ start: words[0].start, end: words.at(-1).end }];
          const hint = hints.find(
            (h) =>
              h.base_id === cue.id &&
              Math.abs(h.source_spans[0].start - spans[0].start) < 0.00001 &&
              Math.abs(h.source_spans.at(-1).end - spans[0].end) < 0.00001 &&
              h.plain ===
                words
                  .map((w) => w.text)
                  .join("")
                  .replace(/\s/g, ""),
          );
          const text =
            hint?.text || wrapPreview(words.map((w) => w.text).join(""));
          out.push({
            id: cue.id + ":" + k,
            base_id: cue.id,
            start: p.output_start + words[0].start - p.source_start,
            end: p.output_start + words.at(-1).end - p.source_start,
            text,
            highlights: (cue.highlights || []).filter((h) =>
              text.replaceAll("\n", "").includes(h),
            ),
            source_spans: spans,
            needs_review: !!(cue.review_reason || partial.length),
            review_reason:
              cue.review_reason ||
              (partial.length ? "剪輯點切入詞語，請試聽確認。" : ""),
          });
        } else if (partial.length) {
          const a = Math.max(
              p.source_start,
              Math.min(...partial.map((x) => x.start)),
            ),
            b = Math.min(p.source_end, Math.max(...partial.map((x) => x.end)));
          out.push({
            id: cue.id + ":" + k,
            base_id: cue.id,
            start: p.output_start + a - p.source_start,
            end: p.output_start + b - p.source_start,
            text: cue.text,
            highlights: cue.highlights || [],
            source_spans: [{ start: a, end: b }],
            needs_review: true,
            review_reason: "剪輯點切入詞語，請手動確認。",
          });
        }
      });
    } else {
      const parts = [];
      for (const s of cue.spans)
        for (const p of map) {
          const a = Math.max(s.start, p.source_start),
            b = Math.min(s.end, p.source_end);
          if (b > a + 0.00001)
            parts.push({
              start: p.output_start + a - p.source_start,
              end: p.output_start + b - p.source_start,
              span: { start: a, end: b },
            });
        }
      if (!parts.length) continue;
      parts.sort((a, b) => a.start - b.start);
      const lost =
        cue.spans.reduce((v, s) => v + s.end - s.start, 0) -
          parts.reduce((v, s) => v + s.end - s.start, 0) >
        0.001;
      const gap = parts.some((p, i) => i && p.start - parts[i - 1].end > 0.001);
      out.push({
        id: cue.id,
        base_id: cue.id,
        start: parts[0].start,
        end: parts.at(-1).end,
        text: cue.text,
        highlights: cue.highlights || [],
        source_spans: parts.map((p) => p.span),
        needs_review: !!(cue.review_reason || lost || gap),
        review_reason:
          cue.review_reason ||
          (lost || gap ? "剪輯改變人工字幕內容，請重新確認。" : ""),
      });
    }
  }
  return out.sort((a, b) => a.start - b.start || a.end - b.end);
}
export function derive(state, hints = []) {
  const map = buildMap(state.duration, state.cuts);
  return {
    map,
    cues: mapSources(state.sources, map, hints),
    duration: map.at(-1).output_end,
  };
}
export function validateCues(cues, duration, reviewed = false) {
  let end = 0;
  for (const c of cues) {
    if (
      !finite(c.start) ||
      !finite(c.end) ||
      c.start < end - 0.00001 ||
      c.end <= c.start ||
      c.end > duration + 0.00001
    )
      throw Error("字幕重疊或超出影片，請調整邊界。");
    if (!c.text.trim()) throw Error("字幕不可空白。");
    if (reviewed && c.needs_review) throw Error("請先試聽並確認標示的字幕。");
    end = c.end;
  }
}
export function initialState(doc) {
  return copy({
    duration: doc.duration,
    sources: doc.sources,
    cuts: doc.cuts,
    corrections: doc.corrections,
    style: doc.style,
    enabled: doc.enabled,
  });
}
function manualFrom(cue, map, idFactory) {
  return {
    id: idFactory(),
    spans: inverse(cue.start, cue.end, map),
    text: cue.text,
    highlights: cue.highlights || [],
    atoms: [],
    manual: true,
    review_reason: cue.needs_review ? cue.review_reason : "",
    correction_ref: "",
  };
}
export function replaceCue(state, cueId, patch, idFactory = newId, hints = []) {
  const next = copy(state),
    d = derive(state, hints),
    selected = d.cues.find((c) => c.id === cueId);
  if (!selected) throw Error("請先選擇字幕。");
  const visible = d.cues.filter((c) => c.base_id === selected.base_id),
    original = state.sources.find((s) => s.id === selected.base_id);
  if (
    Object.keys(patch).length &&
    Object.keys(patch).every((k) => k === "highlights")
  ) {
    next.sources.find((s) => s.id === selected.base_id).highlights = copy(
      patch.highlights || [],
    );
    return { state: next, id: cueId };
  }
  if (original?.manual && visible.length === 1 && !selected.needs_review) {
    const edited = { ...selected, ...patch },
      source = next.sources.find((s) => s.id === selected.base_id);
    source.spans = inverse(edited.start, edited.end, d.map);
    source.text = edited.text;
    source.highlights = edited.highlights || [];
    source.review_reason = "";
    source.correction_ref = "";
    return { state: next, id: cueId };
  }
  next.sources = next.sources.filter((s) => s.id !== selected.base_id);
  let selectedId = "";
  for (const cue of visible) {
    const edited = cue.id === cueId ? { ...cue, ...patch } : cue;
    const source = manualFrom(edited, d.map, idFactory);
    if (cue.id === cueId) {
      source.review_reason = "";
      selectedId = source.id;
    }
    next.sources.push(source);
  }
  // Retain completely cut-away acoustic words for future undo/restore.
  const hidden = (original?.atoms || []).filter(
    (a) =>
      !visible.some((c) =>
        c.source_spans.some(
          (s) => Math.min(a.end, s.end) > Math.max(a.start, s.start),
        ),
      ),
  );
  if (hidden.length)
    next.sources.push({
      id: idFactory(),
      spans: [{ start: hidden[0].start, end: hidden.at(-1).end }],
      text: wrapPreview(hidden.map((a) => a.text).join("")),
      highlights: [],
      atoms: hidden,
      manual: false,
      review_reason: "",
      correction_ref: "",
    });
  return { state: next, id: selectedId };
}
export function splitCue(
  state,
  cueId,
  time,
  index,
  idFactory = newId,
  hints = [],
) {
  const d = derive(state, hints),
    cue = d.cues.find((c) => c.id === cueId);
  if (!cue || time <= cue.start + 0.05 || time >= cue.end - 0.05)
    throw Error("請將播放位置移到字幕中間再拆分。");
  const text = cue.text;
  if (!(index > 0 && index < text.length)) {
    const breaks =
      typeof Intl.Segmenter === "function"
        ? [
            ...new Intl.Segmenter("zh-Hant", { granularity: "word" }).segment(
              text,
            ),
          ]
            .map((s) => s.index)
            .filter((i) => i > 0)
        : [];
    index =
      breaks.sort(
        (a, b) => Math.abs(a - text.length / 2) - Math.abs(b - text.length / 2),
      )[0] || Math.floor(text.length / 2);
  }
  const first = text.slice(0, index).trim(),
    second = text.slice(index).trim();
  if (!first || !second) throw Error("拆分後兩段都需要文字。");
  const replaced = replaceCue(
    state,
    cueId,
    {
      end: time,
      text: first,
      highlights: cue.highlights.filter((h) => first.includes(h)),
    },
    idFactory,
    hints,
  );
  replaced.state.sources.push({
    id: idFactory(),
    spans: inverse(time, cue.end, d.map),
    text: second,
    highlights: cue.highlights.filter((h) => second.includes(h)),
    atoms: [],
    manual: true,
    review_reason: "",
    correction_ref: "",
  });
  return replaced;
}
export function mergeCue(state, cueId, idFactory = newId, hints = []) {
  const d = derive(state, hints),
    index = d.cues.findIndex((c) => c.id === cueId),
    a = d.cues[index],
    b = d.cues[index + 1];
  if (!a || !b) throw Error("沒有下一段可合併。");
  // Materialize all currently visible captions, preserving hidden sources.
  const visibleIds = new Set(d.cues.map((c) => c.base_id));
  const next = copy(state);
  next.sources = next.sources.filter((c) => !visibleIds.has(c.id));
  let selected = "";
  for (let i = 0; i < d.cues.length; i++) {
    const c =
      i === index
        ? {
            ...a,
            end: b.end,
            text: a.text.replace(/\n$/, "") + "\n" + b.text,
            highlights: [...new Set([...a.highlights, ...b.highlights])],
            needs_review: false,
          }
        : d.cues[i];
    if (i === index + 1) continue;
    const source = manualFrom(c, d.map, idFactory);
    if (i === index) selected = source.id;
    next.sources.push(source);
  }
  for (const source of state.sources.filter((s) => visibleIds.has(s.id))) {
    const hidden = (source.atoms || []).filter(
      (a) =>
        !d.cues.some(
          (c) =>
            c.base_id === source.id &&
            c.source_spans.some(
              (s) => Math.min(a.end, s.end) > Math.max(a.start, s.start),
            ),
        ),
    );
    if (hidden.length)
      next.sources.push({
        ...copy(source),
        id: idFactory(),
        atoms: hidden,
        spans: [{ start: hidden[0].start, end: hidden.at(-1).end }],
        text: wrapPreview(hidden.map((a) => a.text).join("")),
      });
  }
  return { state: next, id: selected };
}
export function chooseCorrection(state, id, decision, variants) {
  const next = copy(state),
    correction = next.corrections.find((c) => c.id === id);
  if (!correction) throw Error("校正項目不存在。");
  const cue = next.sources.find((c) => c.id === correction.cue_id);
  if (!cue || (cue.manual && !cue.correction_ref))
    throw Error("此段已有人工修改，人工內容優先保留。");
  const replacement = variants[id]?.[decision];
  if (!replacement) throw Error("校正選項無效。");
  next.sources[next.sources.indexOf(cue)] = copy(replacement);
  correction.decision = decision;
  return next;
}
export class History {
  constructor(state) {
    this.state = copy(state);
    this.past = [];
    this.future = [];
    this.lastKind = "";
    this.lastTime = 0;
  }
  commit(next, kind = "", time = Date.now()) {
    if (!(kind && kind === this.lastKind && time - this.lastTime < 700)) {
      this.past.push(copy(this.state));
      if (this.past.length > 50) this.past.shift();
    }
    this.state = copy(next);
    this.future = [];
    this.lastKind = kind;
    this.lastTime = time;
    return this.state;
  }
  undo() {
    if (!this.past.length) return this.state;
    this.future.push(copy(this.state));
    this.state = this.past.pop();
    this.lastKind = "";
    return this.state;
  }
  redo() {
    if (!this.future.length) return this.state;
    this.past.push(copy(this.state));
    this.state = this.future.pop();
    this.lastKind = "";
    return this.state;
  }
}
export function makeRequest(doc, state, operationId = newId()) {
  const d = derive(state);
  validateCues(d.cues, d.duration);
  return {
    protocol: 1,
    operation_id: operationId,
    base_revision: doc.base_revision,
    source_sha256: doc.source_sha256,
    captions: state.sources.map((c) => ({
      id: c.id,
      spans: c.spans,
      text: c.text,
      highlights: c.highlights || [],
      confirmed: !c.review_reason,
    })),
    cuts: state.cuts.map((c) => ({
      id: c.id,
      start: c.start,
      end: c.end,
      selected: c.selected,
      confirmed: c.confirmed,
    })),
    corrections: state.corrections.map((c) => ({
      id: c.id,
      decision: c.decision,
    })),
    style: state.style,
    enabled: state.enabled,
  };
}

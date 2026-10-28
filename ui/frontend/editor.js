export default function (component) {
  const { parentElement, data, setTriggerValue } = component;
  let root = parentElement.querySelector(".tva-editor");
  if (root?.controller) {
    root.controller.update(data);
    return () => {
      root.controller.store();
      setTimeout(() => {
        if (!root.isConnected) root.controller.dispose();
      }, 0);
    };
  }
  root = document.createElement("section");
  root.className = "tva-editor";
  root.setAttribute("aria-label", "視覺化影片與字幕編輯器");
  parentElement.appendChild(root);
  // This template is fixed, trusted application markup. All customer text below
  // is inserted with textContent/value, never innerHTML.
  root.innerHTML = `<div class="toolbar"><strong>影片與字幕編輯器</strong><span class="status" role="status"></span><div class="actions"><button data-action="undo">撤銷</button><button data-action="redo">重做</button><button data-action="save" class="primary">儲存編輯</button></div></div>
  <div class="notice hidden" role="alert"></div><div class="workspace"><div class="preview"><div class="screen"><video playsinline preload="metadata"></video><div class="overlay"></div></div>
  <div class="controls"><button data-action="play" aria-label="播放或暫停">播放</button><input class="seek" type="range" min="0" step="0.01" value="0" aria-label="影片播放進度"><span class="clock"></span></div>
  <label><input type="checkbox" class="edited-mode" checked> 預覽剪輯後內容</label><p class="hint">瀏覽器用跳轉略過刪除片段，切點可能有短暫延遲；正式成品由 FFmpeg 精準裁切。</p></div>
  <div class="inspector"><div class="tabs" role="tablist"><button data-tab="caption" role="tab" aria-selected="true">字幕</button><button data-tab="cuts" role="tab" aria-selected="false">粗剪</button><button data-tab="correction" role="tab" aria-selected="false">腳本校正</button></div>
  <div data-panel="caption"><label>字幕文字<textarea class="caption-input" aria-label="字幕文字"></textarea></label><div class="row"><label>開始秒數<input class="start-time" type="number" min="0" step=".01"></label><label>結束秒數<input class="end-time" type="number" min="0" step=".01"></label></div>
  <div class="actions"><button data-action="split">依播放位置拆分</button><button data-action="merge">合併下一段</button><button data-action="review">此段已試聽確認</button></div><label>黃色重點（多個用｜分隔）<input class="highlights" type="text"></label><button data-action="highlight">將選取文字標黃</button><label>原始辨識參考</label><div class="raw"></div>
  <div class="row"><label>字幕樣式<select class="preset"><option value="basic">基本字幕</option><option value="emphasis">重點字幕</option></select></label><label><input class="enabled" type="checkbox"> 顯示／輸出字幕</label></div>
  <label>字體大小 <input class="font-size" type="range" min="24" max="96" step="1"></label><label>距離底部 <input class="bottom" type="range" min="5" max="35" step="1"></label><div class="cue-list" aria-label="字幕片段清單"></div></div>
  <div data-panel="cuts" class="hidden"><div class="cut-summary"></div><div class="actions"><button data-action="listen-cut">試看此片段</button><button data-action="toggle-cut">確認刪除／保留</button></div><p class="hint">紅色為重講建議，灰色為停頓；斜線表示已確認刪除。原片永遠保留，可取消刪除。</p><div class="row"><label>手動刪除開始<input class="manual-start" type="number" min="0" step=".01" value="0"></label><label>手動刪除結束<input class="manual-end" type="number" min="0" step=".01" value="1"></label></div><button data-action="manual-cut">確認加入刪除片段</button></div>
  <div data-panel="correction" class="hidden"><p class="hint">腳本只供參考。數字、價格、尺寸與近音差異需確認；人工修字優先，原始辨識不會改動。</p><div class="correction-list"></div></div></div></div>
  <div class="timeline-title"><strong>原片內容與建議</strong><span class="hint">綠：保留　紅：重講　灰：停頓</span></div><div class="overview" aria-label="原片剪輯建議軌道"><div class="overview-head"></div></div>
  <div class="timeline-title"><strong>剪輯後影片／字幕</strong><label>縮放 <input class="zoom" type="range" min="15" max="160" value="65" aria-label="時間軸縮放"></label></div><div class="timeline"><div class="tracks"><div class="ruler"></div><div class="keep-track"></div><div class="caption-track" aria-label="字幕時間軸"></div><div class="playhead"></div></div></div>
  <div class="actions" style="margin-top:12px"><button class="primary" data-action="export">儲存並輸出 MP4</button><button data-action="srt">儲存並下載 SRT</button><button data-action="draft">下載瀏覽器草稿</button><button class="reload hidden" data-action="reload">重新載入專案版本</button></div>
  <div class="output-result hidden"><h4>已輸出的 MP4</h4><video class="output-video" controls playsinline preload="metadata"></video></div><details><summary>儲存與操作狀態</summary><p>輸入停止後會保留在此瀏覽器；只有儲存／輸出按鈕才同步專案。共用電腦請妥善保管草稿，雲端仍需另存 JSON 與原片。</p><pre class="metrics"></pre></details>`;
  const q = (s) => root.querySelector(s),
    qa = (s) => [...root.querySelectorAll(s)],
    video = q("video"),
    textarea = q(".caption-input");
  let doc = data,
    history = new History(initialState(doc)),
    derived,
    selected = "",
    selectedCut = "",
    edited = true,
    rawStop = null,
    dirty = false,
    pending = null,
    conflict = false,
    zoom = 65,
    raf = 0,
    saveTimer = 0,
    drag = null,
    caret = 0,
    overlaySignature = "",
    draftBaseRevision = data.base_revision;
  const metrics = {
    edits: 0,
    styles: 0,
    seeks: 0,
    syncs: 0,
    edit_ms: [],
    style_ms: [],
  };
  const storageKey = "talking-video-editor-v1:" + doc.project_id;
  const format = (n) => {
    n = Math.max(0, n || 0);
    return Math.floor(n / 60) + ":" + (n % 60).toFixed(2).padStart(5, "0");
  };
  function notice(text, error = false) {
    q(".notice").textContent = text;
    q(".notice").className =
      "notice" + (text ? "" : " hidden") + (error ? " error" : "");
  }
  function status(text) {
    q(".status").textContent = text;
  }
  function record(kind, started) {
    const a = kind === "style" ? metrics.style_ms : metrics.edit_ms;
    a.push(performance.now() - started);
    if (a.length > 120) a.shift();
    renderMetrics();
  }
  function renderMetrics() {
    const avg = (a) =>
      a.length ? (a.reduce((s, v) => s + v, 0) / a.length).toFixed(2) : "—";
    q(".metrics").textContent =
      `字幕修改：${metrics.edits} 次，平均 ${avg(metrics.edit_ms)} ms\n樣式修改：${metrics.styles} 次，平均 ${avg(metrics.style_ms)} ms\n播放定位：${metrics.seeks} 次\n同步專案：${metrics.syncs} 次（一般互動不會同步）`;
  }
  function store() {
    if (!dirty) return;
    try {
      const value = {
        protocol: 1,
        project_id: doc.project_id,
        sha: doc.source_sha256,
        base_revision: draftBaseRevision,
        time: Date.now(),
        state: history.state,
        past: history.past.slice(-10),
        future: history.future.slice(-10),
        position: currentOutput(),
      };
      const json = JSON.stringify(value);
      if (json.length > 1_500_000) {
        value.past = [];
        value.future = [];
      }
      localStorage.setItem(storageKey, JSON.stringify(value));
      if (!pending) status("已保留瀏覽器草稿，尚未儲存到專案");
    } catch {
      status("瀏覽器草稿空間不足，請儲存專案或下載草稿");
    }
  }
  function changed(next, kind = "change", id = "") {
    const stable = id === selected;
    history.commit(next, kind);
    dirty = true;
    if (id) selected = id;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(store, 800);
    status("尚未儲存");
    render(
      kind === "style"
        ? "style"
        : kind.startsWith("text") && stable
          ? "text"
          : "all",
    );
  }
  function currentOutput() {
    return edited
      ? toOutput(video.currentTime || 0, derived.map)
      : video.currentTime || 0;
  }
  function seek(time) {
    metrics.seeks++;
    rawStop = null;
    if (edited)
      video.currentTime = toSource(
        Math.max(0, Math.min(time, derived.duration)),
        derived.map,
      );
    else video.currentTime = Math.max(0, Math.min(time, doc.duration));
    paint();
    renderMetrics();
  }
  function choose(id, jump = true) {
    selected = id;
    const c = derived.cues.find((c) => c.id === id);
    if (c && jump) {
      edited = true;
      q(".edited-mode").checked = true;
      seek(c.start + 0.001);
    }
    renderInspector();
    renderTracks();
  }
  function changeCue(patch, kind = "caption") {
    const started = performance.now();
    try {
      const previous = selected,
        r = replaceCue(
          history.state,
          selected,
          patch,
          newId,
          doc.layout_hints || [],
        );
      changed(r.state, kind, r.id);
      if (previous !== selected) renderTracks();
      metrics.edits++;
      record("edit", started);
    } catch (e) {
      notice(e.message, true);
    }
  }
  function renderInspector() {
    const c = derived.cues.find((c) => c.id === selected);
    for (const el of [
      textarea,
      q(".start-time"),
      q(".end-time"),
      q(".highlights"),
    ])
      el.disabled = !c;
    if (c) {
      if (textarea.value !== c.text) textarea.value = c.text;
      q(".start-time").value = c.start.toFixed(3);
      q(".end-time").value = c.end.toFixed(3);
      q(".highlights").value = c.highlights.join("｜");
      const raw = (doc.raw_segments || doc.original_cues || [])
        .filter((s) =>
          s.spans.some((a) =>
            c.source_spans.some(
              (b) => Math.min(a.end, b.end) > Math.max(a.start, b.start),
            ),
          ),
        )
        .map((s) => s.text)
        .join("\n");
      q(".raw").textContent = raw || "此段沒有對應的辨識片段";
      if (c.needs_review) notice(c.review_reason);
    }
    q(".preset").value = history.state.style.preset;
    q(".enabled").checked = history.state.enabled;
    q(".font-size").value = history.state.style.font_size;
    q(".bottom").value = history.state.style.bottom_percent;
    q("[data-action=undo]").disabled = !history.past.length;
    q("[data-action=redo]").disabled = !history.future.length;
    q("[data-action=review]").disabled = !c?.needs_review;
    const cut = history.state.cuts.find((c) => c.id === selectedCut);
    q(".cut-summary").textContent = cut
      ? `${format(cut.start)}～${format(cut.end)}｜${cut.selected ? "已確認刪除" : "保留"}\n${cut.reason || "人工剪輯"}`
      : "請在原片軌道點選紅色或灰色片段";
    for (const action of ["listen-cut", "toggle-cut"])
      q(`[data-action=${action}]`).disabled = !cut;
  }
  function renderCorrections() {
    const container = q(".correction-list");
    container.replaceChildren();
    for (const correction of history.state.corrections) {
      const card = document.createElement("div");
      card.className = "correction-card";
      const label = document.createElement("strong");
      label.textContent = {
        auto: "自動校正",
        review: "建議確認",
        keep: "保留原文",
      }[correction.status];
      card.append(label);
      for (const [label, value] of [
        ["辨識", correction.original],
        ["校正", correction.proposed],
        ["腳本參考", correction.reference],
        ["說明", correction.reason],
      ]) {
        const p = document.createElement("p");
        p.textContent = label + "：" + value;
        card.append(p);
      }
      const source = history.state.sources.find(
          (s) => s.id === correction.cue_id,
        ),
        manual = !source || (source.manual && !source.correction_ref);
      const state = document.createElement("span");
      state.className = "badge";
      state.textContent = manual
        ? "人工修改優先"
        : { accepted: "已採用", rejected: "保留辨識", pending: "待確認" }[
            correction.decision
          ];
      card.append(state);
      if (correction.status !== "keep")
        for (const [text, decision] of [
          ["採用校正", "accepted"],
          ["撤銷／保留辨識", "rejected"],
        ]) {
          const b = document.createElement("button");
          b.textContent = text;
          b.disabled = manual;
          b.onclick = () => {
            try {
              changed(
                chooseCorrection(
                  history.state,
                  correction.id,
                  decision,
                  doc.variants,
                ),
                "correction",
              );
            } catch (e) {
              notice(e.message, true);
            }
          };
          card.append(b);
        }
      container.append(card);
    }
    if (!container.children.length)
      container.textContent = "先產生字幕後，這裡會顯示腳本比對與校正。";
  }
  function renderTracks() {
    const over = q(".overview");
    over.querySelectorAll(".cut").forEach((e) => e.remove());
    for (const cut of history.state.cuts) {
      const b = document.createElement("button");
      b.className =
        "cut" +
        (cut.kind === "silence" ? " silence" : "") +
        (cut.selected ? " removed" : "") +
        (cut.id === selectedCut ? " selected" : "");
      b.style.left = (cut.start / doc.duration) * 100 + "%";
      b.style.width = ((cut.end - cut.start) / doc.duration) * 100 + "%";
      b.title =
        (cut.kind === "silence" ? "停頓" : "重講／人工片段") +
        " " +
        format(cut.start) +
        "～" +
        format(cut.end);
      b.setAttribute("aria-label", b.title);
      b.onclick = () => {
        selectedCut = cut.id;
        tab("cuts");
        renderInspector();
        renderTracks();
      };
      over.append(b);
    }
    q(".tracks").style.width = Math.max(derived.duration * zoom, 500) + "px";
    const ruler = q(".ruler");
    ruler.replaceChildren();
    const step = zoom < 30 ? 5 : 1;
    for (let t = 0; t <= derived.duration; t += step) {
      const tick = document.createElement("span");
      tick.className = "tick";
      tick.style.left = t * zoom + "px";
      tick.textContent = format(t);
      ruler.append(tick);
    }
    q(".keep-track").replaceChildren();
    derived.map.forEach((p, i) => {
      const el = document.createElement("div");
      el.className = "keep";
      el.style.left = p.output_start * zoom + "px";
      el.style.width = (p.output_end - p.output_start) * zoom + "px";
      el.textContent = "保留 " + (i + 1);
      el.title = `原片 ${format(p.source_start)}～${format(p.source_end)}`;
      q(".keep-track").append(el);
    });
    const track = q(".caption-track");
    track.replaceChildren();
    for (const c of derived.cues) {
      const el = document.createElement("div");
      el.className =
        "cue" +
        (c.id === selected ? " active" : "") +
        (c.needs_review ? " review" : "");
      el.dataset.id = c.id;
      el.style.left = c.start * zoom + "px";
      el.style.width = (c.end - c.start) * zoom + "px";
      el.tabIndex = 0;
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", "字幕：" + c.text);
      for (const side of ["start", "end"]) {
        const h = document.createElement("span");
        h.className = "handle " + side;
        h.dataset.side = side;
        h.setAttribute(
          "aria-label",
          "拖曳字幕" + (side === "start" ? "開始" : "結束"),
        );
        el.append(h);
      }
      const text = document.createElement("span");
      text.className = "cue-text";
      text.textContent = c.text;
      el.append(text);
      el.onkeydown = (e) => {
        if (e.key === "Enter") choose(c.id);
      };
      el.onpointerdown = (e) => startDrag(e, c);
      track.append(el);
    }
    const list = q(".cue-list");
    list.replaceChildren();
    const center = derived.cues.findIndex((c) => c.id === selected),
      from = Math.max(0, center - 5);
    for (const c of derived.cues.slice(from, from + 16)) {
      const b = document.createElement("button");
      b.className = "cue-item";
      b.textContent = `${format(c.start)} ${c.text.replaceAll("\n", " ")}`;
      b.onclick = () => choose(c.id);
      list.append(b);
    }
    paint();
  }
  function render(kind = "all") {
    try {
      if (kind === "text" && derived) {
        const c = derived.cues.find((c) => c.id === selected),
          s = history.state.sources.find((s) => s.id === c?.base_id);
        if (c && s) {
          c.text = s.text;
          c.highlights = s.highlights;
        } else derived = derive(history.state, doc.layout_hints || []);
      } else if (kind !== "style" || !derived)
        derived = derive(history.state, doc.layout_hints || []);
      validateCues(derived.cues, derived.duration);
      notice("");
    } catch (e) {
      notice(e.message, true);
      try {
        derived = derive(history.state, doc.layout_hints || []);
      } catch {
        return;
      }
    }
    if (!derived.cues.some((c) => c.id === selected))
      selected = derived.cues[0]?.id || "";
    q(".seek").max = edited ? derived.duration : doc.duration;
    if (kind === "text") {
      const c = derived.cues.find((c) => c.id === selected),
        block = [...q(".caption-track").children].find(
          (e) => e.dataset.id === selected,
        );
      if (block && c) block.querySelector(".cue-text").textContent = c.text;
      paint();
    } else if (kind === "style") {
      paint();
    } else {
      renderInspector();
      renderTracks();
      renderCorrections();
    }
    q("[data-action=undo]").disabled = !history.past.length;
    q("[data-action=redo]").disabled = !history.future.length;
    q("[data-action=save]").disabled = !!pending || conflict;
    q("[data-action=export]").disabled = !!pending || conflict;
    q("[data-action=srt]").disabled = !!pending || conflict;
  }
  function paint() {
    if (!derived) return;
    let raw = video.currentTime || 0;
    if (rawStop !== null && raw >= rawStop) {
      video.pause();
      rawStop = null;
      edited = q(".edited-mode").checked;
    }
    if (edited && !video.seeking) {
      const p = derived.map.find(
        (p) => raw >= p.source_start - 0.001 && raw < p.source_end - 0.001,
      );
      if (!p) {
        const next = derived.map.find((p) => p.source_start > raw);
        if (next) {
          video.currentTime = next.source_start;
          raw = next.source_start;
        } else if (raw >= derived.map.at(-1).source_end) {
          video.pause();
        }
      }
    }
    const time = toOutput(raw, derived.map);
    q(".seek").value = edited ? time : raw;
    q(".clock").textContent =
      format(edited ? time : raw) +
      " / " +
      format(edited ? derived.duration : doc.duration);
    q("[data-action=play]").textContent = video.paused ? "播放" : "暫停";
    q(".playhead").style.left = time * zoom + "px";
    q(".overview-head").style.left = (raw / doc.duration) * 100 + "%";
    let lo = 0,
      hi = derived.cues.length - 1,
      active = null;
    while (lo <= hi) {
      const m = (lo + hi) >> 1,
        c = derived.cues[m];
      if (time < c.start) hi = m - 1;
      else if (time >= c.end) lo = m + 1;
      else {
        active = c;
        break;
      }
    }
    const overlay = q(".overlay");
    const signature = JSON.stringify([
      history.state.enabled,
      active?.id,
      active?.text,
      active?.highlights,
      history.state.style,
      q(".screen").clientWidth,
    ]);
    if (signature === overlaySignature) return;
    overlaySignature = signature;
    overlay.replaceChildren();
    if (!history.state.enabled || !active) return;
    const text = active.text,
      plain = text.replaceAll("\n", "");
    let marked = new Set();
    if (history.state.style.preset === "emphasis")
      for (const h of active.highlights) {
        let from = 0,
          index;
        while (h && (index = plain.indexOf(h, from)) >= 0) {
          for (let i = index; i < index + h.length; i++) marked.add(i);
          from = index + h.length;
        }
      }
    let cursor = 0,
      span = null,
      previous = null;
    for (const char of text) {
      if (char === "\n") {
        overlay.append(document.createTextNode("\n"));
        span = null;
        previous = null;
        continue;
      }
      const yellow = marked.has(cursor++);
      if (yellow !== previous || !span) {
        span = document.createElement("span");
        if (yellow) span.className = "yellow";
        overlay.append(span);
        previous = yellow;
      }
      span.textContent += char;
    }
    const scale = q(".screen").clientWidth / 1080,
      longest = Math.max(1, ...text.split("\n").map(textWidth)),
      size = Math.min(history.state.style.font_size, Math.floor(972 / longest));
    overlay.style.fontSize = Math.max(16, size) * scale + "px";
    overlay.style.webkitTextStrokeWidth = 3 * scale + "px";
    overlay.style.bottom = history.state.style.bottom_percent + "%";
  }
  function loop() {
    if (!root.isConnected) return;
    paint();
    raf = requestAnimationFrame(loop);
  }
  function tab(name) {
    for (const el of qa("[data-tab]"))
      el.setAttribute("aria-selected", String(el.dataset.tab === name));
    for (const el of qa("[data-panel]"))
      el.classList.toggle("hidden", el.dataset.panel !== name);
  }
  function startDrag(e, cue) {
    e.preventDefault();
    selected = cue.id;
    renderInspector();
    const side = e.target.dataset.side || "move";
    drag = { cue: copy(cue), side, x: e.clientX, delta: 0 };
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    target.onpointermove = (ev) => {
      if (!drag) return;
      drag.delta = (ev.clientX - drag.x) / zoom;
      const move = Math.max(
        -cue.start,
        Math.min(drag.delta, derived.duration - cue.end),
      );
      const a =
        side === "move"
          ? cue.start + move
          : side === "end"
            ? cue.start
            : Math.max(0, Math.min(cue.start + drag.delta, cue.end - 0.08));
      const b =
        side === "move"
          ? cue.end + move
          : side === "start"
            ? cue.end
            : Math.max(
                a + 0.08,
                Math.min(cue.end + drag.delta, derived.duration),
              );
      target.style.left = a * zoom + "px";
      target.style.width = (b - a) * zoom + "px";
      q(".start-time").value = a.toFixed(3);
      q(".end-time").value = b.toFixed(3);
    };
    target.onpointerup = () => {
      if (!drag) return;
      const moved = Math.abs(drag.delta * zoom) > 3;
      drag = null;
      target.onpointermove = null;
      target.onpointerup = null;
      if (moved)
        changeCue(
          {
            start: Number(q(".start-time").value),
            end: Number(q(".end-time").value),
          },
          "drag",
        );
      else choose(cue.id);
    };
  }
  function blobDownload(content, name, type) {
    const url = URL.createObjectURL(new Blob([content], { type })),
      a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  function sync(action) {
    try {
      if (conflict) throw Error("專案版本已更新，請先下載草稿並重新載入。");
      if (pending) return;
      const request = makeRequest(doc, history.state);
      if (action !== "save")
        validateCues(
          derived.cues,
          derived.duration,
          history.state.enabled || action === "srt",
        );
      store();
      pending = {
        id: request.operation_id,
        snapshot: JSON.stringify(history.state),
        action,
      };
      metrics.syncs++;
      status("正在儲存…");
      render();
      setTriggerValue("commit", { action, request });
      renderMetrics();
    } catch (e) {
      notice(e.message, true);
    }
  }
  textarea.oninput = () => {
    caret = textarea.selectionStart;
    const c = derived.cues.find((c) => c.id === selected);
    changeCue(
      {
        text: textarea.value,
        highlights: (c?.highlights || []).filter((h) =>
          textarea.value.replaceAll("\n", "").includes(h),
        ),
      },
      "text",
    );
  };
  textarea.onselect = () => {
    caret = textarea.selectionStart;
  };
  q(".start-time").onchange = () =>
    changeCue({ start: Number(q(".start-time").value) }, "time");
  q(".end-time").onchange = () =>
    changeCue({ end: Number(q(".end-time").value) }, "time");
  q(".highlights").onchange = () => {
    const c = derived.cues.find((c) => c.id === selected),
      parts = q(".highlights")
        .value.split("｜")
        .map((s) => s.trim())
        .filter(Boolean);
    if (parts.some((h) => !c?.text.replaceAll("\n", "").includes(h))) {
      notice("重點必須是字幕已有的文字。", true);
      return;
    }
    changeCue({ highlights: parts }, "highlight");
  };
  for (const [selector, key, convert] of [
    [".preset", "preset", (v) => v],
    [".font-size", "font_size", Number],
    [".bottom", "bottom_percent", Number],
  ])
    q(selector).oninput = (e) => {
      const start = performance.now(),
        s = copy(history.state);
      s.style[key] = convert(e.target.value);
      changed(s, "style");
      metrics.styles++;
      record("style", start);
    };
  q(".enabled").onchange = (e) => {
    const s = copy(history.state);
    s.enabled = e.target.checked;
    changed(s, "style");
  };
  q(".zoom").oninput = (e) => {
    zoom = Number(e.target.value);
    renderTracks();
  };
  q(".edited-mode").onchange = (e) => {
    edited = e.target.checked;
    rawStop = null;
    q(".seek").max = edited ? derived.duration : doc.duration;
    paint();
  };
  q(".seek").oninput = (e) => seek(Number(e.target.value));
  q(".ruler").onclick = (e) =>
    seek((e.clientX - q(".tracks").getBoundingClientRect().left) / zoom);
  root.addEventListener("click", (e) => {
    const b = e.target.closest("[data-action],[data-tab]");
    if (!b) return;
    if (b.dataset.tab) {
      tab(b.dataset.tab);
      return;
    }
    try {
      switch (b.dataset.action) {
        case "play":
          video.paused
            ? video
                .play()
                .catch(() => notice("請再次按播放，允許瀏覽器播放影片。"))
            : video.pause();
          break;
        case "undo":
          history.undo();
          dirty = true;
          store();
          render();
          break;
        case "redo":
          history.redo();
          dirty = true;
          store();
          render();
          break;
        case "save":
        case "export":
        case "srt":
          sync(b.dataset.action);
          break;
        case "draft":
          blobDownload(
            JSON.stringify(
              {
                project_id: doc.project_id,
                source_sha256: doc.source_sha256,
                base_revision: draftBaseRevision,
                state: history.state,
              },
              null,
              2,
            ),
            "影片編輯草稿.json",
            "application/json",
          );
          break;
        case "reload":
          history = new History(initialState(doc));
          dirty = conflict = false;
          pending = null;
          draftBaseRevision = doc.base_revision;
          localStorage.removeItem(storageKey);
          q(".reload").classList.add("hidden");
          notice("");
          render();
          status("已重新載入專案版本");
          break;
        case "split": {
          const r = splitCue(
            history.state,
            selected,
            toOutput(video.currentTime || 0, derived.map),
            caret,
            newId,
            doc.layout_hints || [],
          );
          changed(r.state, "split", r.id);
          break;
        }
        case "merge": {
          const r = mergeCue(
            history.state,
            selected,
            newId,
            doc.layout_hints || [],
          );
          changed(r.state, "merge", r.id);
          break;
        }
        case "review":
          changeCue({}, "review");
          break;
        case "highlight": {
          const c = derived.cues.find((c) => c.id === selected),
            text = textarea.value
              .slice(textarea.selectionStart, textarea.selectionEnd)
              .replaceAll("\n", "");
          if (!text) throw Error("請先在字幕文字中選取要標黃的字。");
          changeCue(
            { highlights: [...new Set([...c.highlights, text])] },
            "highlight",
          );
          break;
        }
        case "listen-cut": {
          const c = history.state.cuts.find((c) => c.id === selectedCut);
          edited = false;
          video.currentTime = c.start;
          rawStop = c.end;
          video.play().catch(() => notice("請按播放查看片段。"));
          break;
        }
        case "toggle-cut": {
          const s = copy(history.state),
            c = s.cuts.find((c) => c.id === selectedCut);
          c.selected = !c.selected;
          c.confirmed = c.selected;
          changed(s, "cut");
          break;
        }
        case "manual-cut": {
          const s = copy(history.state),
            start = Number(q(".manual-start").value),
            end = Number(q(".manual-end").value);
          if (!(end > start && start >= 0 && end <= doc.duration))
            throw Error("請確認手動刪除範圍。");
          const id = newId();
          s.cuts.push({
            id,
            start,
            end,
            kind: "manual",
            reason: "人工確認刪除",
            selected: true,
            confirmed: true,
            requires_review: true,
          });
          selectedCut = id;
          changed(s, "cut");
          break;
        }
      }
    } catch (error) {
      notice(error.message, true);
    }
  });
  for (const el of qa(".tabs button")) el.onclick = () => tab(el.dataset.tab);
  const unload = (e) => {
    if (dirty) {
      store();
      e.preventDefault();
      e.returnValue = "";
    }
  };
  window.addEventListener("beforeunload", unload);
  const sourceUrl = new URL(
    (doc.media_url || "").replace(/^\//, ""),
    window.location.href,
  ).href;
  video.src = sourceUrl;
  function size() {
    const aspect = doc.video.width / doc.video.height,
      available = q(".preview").clientWidth - 20;
    const w = Math.min(available, 420 * aspect);
    q(".screen").style.width = w + "px";
    q(".screen").style.aspectRatio = String(aspect);
    paint();
  }
  const observer = new ResizeObserver(size);
  observer.observe(q(".preview"));
  video.onloadedmetadata = () => {
    size();
    paint();
  };
  video.onpause = paint;
  video.onplay = paint;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (
      saved &&
      saved.sha === doc.source_sha256 &&
      Date.now() - saved.time < 7 * 86400000
    ) {
      history = new History(saved.state);
      history.past = saved.past || [];
      history.future = saved.future || [];
      dirty = true;
      draftBaseRevision = saved.base_revision;
      if (saved.base_revision === doc.base_revision) {
        status("已恢復瀏覽器草稿");
      } else {
        conflict = true;
        notice(
          "此瀏覽器有較舊草稿，先下載草稿，再重新載入目前專案版本。",
          true,
        );
        q(".reload").classList.remove("hidden");
      }
    }
  } catch {
    status("未載入瀏覽器草稿");
  }
  function outputPlayer() {
    const player = q(".output-video");
    q(".output-result").classList.toggle("hidden", !doc.output_url);
    if (doc.output_url) {
      const url = new URL(
        doc.output_url.replace(/^\//, ""),
        window.location.href,
      ).href;
      if (player.src !== url) player.src = url;
    }
  }
  function update(next) {
    const before = doc;
    doc = next;
    outputPlayer();
    if (pending && doc.outcome?.operation_id === pending.id) {
      const response = doc.outcome;
      if (response.error) {
        pending = null;
        if (response.conflict) {
          conflict = true;
          q(".reload").classList.remove("hidden");
        }
        status("未能完成；瀏覽器草稿仍保留");
        render();
        notice(response.error, true);
        return;
      }
      const same = JSON.stringify(history.state) === pending.snapshot,
        action = pending.action;
      draftBaseRevision = doc.base_revision;
      if (same) {
        history.state = initialState(doc);
        dirty = false;
        localStorage.removeItem(storageKey);
      } else {
        dirty = true;
        store();
      }
      pending = null;
      status(dirty ? "已儲存，另有新修改" : "已儲存到專案");
      if (action === "srt" && response.srt)
        blobDownload(
          "\ufeff" + response.srt,
          "口播字幕.srt",
          "application/x-subrip",
        );
      render();
      notice(response.message || "");
    } else if (doc.base_revision !== before.base_revision) {
      if (dirty) {
        conflict = true;
        q(".reload").classList.remove("hidden");
        notice("專案版本已更新；草稿保留，請下載後重新載入。", true);
      } else {
        history = new History(initialState(doc));
        render();
      }
    } else if (doc.outcome?.error) notice(doc.outcome.error, true);
  }
  root.controller = {
    update,
    store,
    dispose() {
      cancelAnimationFrame(raf);
      clearTimeout(saveTimer);
      observer.disconnect();
      window.removeEventListener("beforeunload", unload);
    },
  };
  render();
  renderMetrics();
  size();
  outputPlayer();
  loop();
  if (!dirty && !conflict) status("已載入專案，可直接播放與編輯");
  return () => {
    store();
    setTimeout(() => {
      if (!root.isConnected) root.controller.dispose();
    }, 0);
  };
}

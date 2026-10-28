"""Simple persisted caption editor. Reruns never perform ASR or render media."""
from pathlib import Path
import pandas as pd
import streamlit as st
from core.subtitles.service import generate, save_edits, save_preferences, delivery_cues, delivery_signature
from core.subtitles.mapping import map_captions, time_map
from core.subtitles.formats import srt
from core.subtitles.burn import preview_frame, prune_previews
from core.subtitles.schemas import CaptionStyle
from core.video.errors import VideoError


def environment_check(assets):
    with st.expander('字幕環境檢查（不使用你的影片）'):
        st.caption('用2秒合成示範檢查繁體字型、黃色重點、剪輯後時間、SRT及帶／不帶字幕MP4；不新增正式專案，也不呼叫AI或語音辨識。')
        if st.button('檢查字幕與中文字型'):
            from core.subtitles.diagnostic import inspect_environment
            with st.spinner('正在檢查字幕輸出環境…'):
                st.session_state.caption_environment_result = inspect_environment(assets.root)
        result = st.session_state.get('caption_environment_result')
        if result:
            st.success(f'字幕輸出檢查通過｜字型：{result["font"]}｜剪輯後 {result["duration"]:.2f} 秒')
            st.image(result['frame'], width=240)
            st.video(result['captioned'], width=240)
            st.download_button('下載字幕測試 MP4', result['captioned'], file_name='字幕環境測試.mp4', mime='video/mp4', on_click='ignore')
            st.download_button('下載無字幕測試 MP4', result['plain'], file_name='無字幕環境測試.mp4', mime='video/mp4', on_click='ignore')
            st.download_button('下載測試 SRT', result['srt'], file_name='字幕環境測試.srt', mime='application/x-subrip', on_click='ignore')


def render(project, manager, assets):
    st.subheader('五、自動字幕')
    st.caption('字幕使用實際口播辨識，不使用原稿代替，也不呼叫 Gemini。時間顯示為剪輯後影片的秒數。')
    if project.subtitles is None:
        if not project.transcript or not project.transcript.segments:
            st.info('先按「開始分析」完成語音辨識，再產生字幕；無聲影片仍可輸出無字幕 MP4。')
            return
        if st.button('由現有辨識產生字幕', type='primary'):
            generate(project, manager)
            st.rerun()
        return
    track, timeline = project.subtitles, project.timelines[-1]
    enabled = st.checkbox('輸出影片開啟字幕', value=track.enabled, key=f'caption_enabled_{project.id}_{track.revision}')
    if enabled != track.enabled:
        save_preferences(project, manager, enabled=enabled)
        st.rerun()
    cues = map_captions(track, timeline)
    if any(c.needs_review for c in cues):
        st.warning('有字幕需要重新確認：可能缺少詞語時間，或剪輯已改變人工修字涵蓋的內容。請修正文字／時間並勾選「已確認」，再保存。')
    st.caption('可直接修字、修改時間，或新增／刪除列來拆分與合併字幕。建議每段1～2行、每行約12個中文字；可在文字中換行。')
    rows = [{'字幕ID': c.id, '開始（秒）': c.start, '結束（秒）': c.end, '字幕文字': c.text,
             '黃色重點': '｜'.join(c.highlights), '已確認': not c.needs_review, '提醒': c.review_reason} for c in cues]
    key = f'subtitle_{project.id}_{track.revision}_{timeline.number}'
    with st.form(key):
        preset = st.selectbox('字幕樣式', ['基本字幕', '重點字幕'], index=1 if track.style.preset == 'emphasis' else 0)
        size = st.slider('字體大小', 24, 96, value=track.style.font_size)
        bottom = st.slider('距離底部（畫面百分比）', 5.0, 35.0, value=float(track.style.bottom_percent), step=1.0)
        edited = st.data_editor(pd.DataFrame(rows, columns=['字幕ID', '開始（秒）', '結束（秒）', '字幕文字', '黃色重點', '已確認', '提醒']),
            num_rows='dynamic', hide_index=True, use_container_width=True, disabled=['字幕ID', '提醒'],
            column_config={'字幕ID': None, '開始（秒）': st.column_config.NumberColumn(min_value=0.0, step=.01, format='%.3f'),
                '結束（秒）': st.column_config.NumberColumn(min_value=0.0, step=.01, format='%.3f'),
                '字幕文字': st.column_config.TextColumn(width='large'), '黃色重點': st.column_config.TextColumn(help='填入這段已有的文字；多個重點用「｜」分隔。樣式B會顯示黃色。')})
        if st.form_submit_button('保存字幕與樣式', type='primary'):
            values = []
            for row in edited.to_dict('records'):
                values.append({'id': row['字幕ID'] if pd.notna(row['字幕ID']) else '', 'start': row['開始（秒）'], 'end': row['結束（秒）'],
                    'text': row['字幕文字'] if pd.notna(row['字幕文字']) else '',
                    'highlights': row['黃色重點'] if pd.notna(row['黃色重點']) else '', 'confirmed': bool(row['已確認'])})
            save_edits(project, manager, values, CaptionStyle(preset='emphasis' if preset == '重點字幕' else 'basic', font_size=size, bottom_percent=bottom), enabled)
            st.rerun()
    st.caption('預覽、SRT與MP4只使用已保存的字幕及目前已確認剪輯；尚未保存的表格調整不會套用。')
    try:
        ready = delivery_cues(project)
    except VideoError as exc:
        st.info(str(exc))
        ready = []
    if ready:
        st.download_button('下載 SRT 字幕', srt(ready, time_map(timeline)[-1].output_end).encode('utf-8-sig'),
            file_name='口播字幕.srt', mime='application/x-subrip', on_click='ignore')
        selected = st.selectbox('預覽哪一段字幕', ready, format_func=lambda c: f'{c.start:.2f}～{c.end:.2f}秒｜{c.text.replace(chr(10), " ")}', key='caption_preview_' + key)
        frame = assets.path(project.id, f'preview-caption-{delivery_signature(project, include_disabled=True)}-{ready.index(selected)}.png')
        if st.button('預覽此段字幕畫面'):
            with st.spinner('正在產生單張畫面，不會重新輸出整支影片…'):
                preview_frame(project, assets, selected, ready, track.style, frame)
                prune_previews(assets, project.id, preserve=frame)
        if frame.exists():
            st.image(str(frame), width=360)
    with st.expander('字幕時間映射與重新產生'):
        st.dataframe([{'原片開始': p.source_start, '原片結束': p.source_end, '輸出開始': p.output_start, '輸出結束': p.output_end} for p in time_map(timeline)], hide_index=True)
        st.caption('修改或恢復剪輯後，字幕依原片座標自動重新映射。若切到人工修字，需重新確認該段。')
        replace = st.checkbox('確認以現有辨識重新產生字幕，取代目前修字與分段', key='replace_' + key)
        if st.button('重新產生字幕', disabled=not replace):
            generate(project, manager, replace=True)
            st.rerun()
        if any(c.review_reason and not c.atoms for c in track.cues):
            st.caption('部分長句只有整句時間。優先保留現有資料；只有按下以下按鈕才補充聲學辨識，不會呼叫 Gemini。')
            supplement = st.checkbox('確認補充缺少的詞語時間並取代字幕修字', key='supplement_' + key)
            if st.button('補充字幕詞語時間', disabled=not supplement):
                from core.transcription.provider import FasterWhisperProvider
                from core.subtitles.alignment import supplement as supplement_alignment
                from ui.settings import ROOT, setting
                asr = FasterWhisperProvider(project.transcript.model, Path(setting('WHISPER_MODEL_DIR', str(ROOT / 'models/whisper'))))
                with st.spinner('補充時間中；只在缺少時間時執行…'):
                    transcript = supplement_alignment(project, assets, asr)
                    generate(project, manager, replace=True, transcript=transcript)
                st.rerun()

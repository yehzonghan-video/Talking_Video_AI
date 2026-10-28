import copy
import hashlib
import importlib.util
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from core.video.assets import LocalAssets
from core.video.ffmpeg import binary
from core.video.errors import VideoError
from core.video.project_manager import VideoProjectManager
from core.video.schemas import AnalysisSettings, Decision
from core.video.uploader import create_project, reattach_source
from core.video.timeline import filename
from core.video.renderer import render as render_video
from core.video.service import analyze, confirm_timeline, restore_timeline
from core.transcription.provider import FasterWhisperProvider
from ui.settings import ROOT, setting
from ui.subtitles import render as render_subtitles
from core.subtitles.service import delivery_cues, delivery_signature


def resources(s):
    database = getattr(s.repo, 'path', Path(setting('DATA_PATH', str(ROOT / 'data/talking_video.db'))))
    return VideoProjectManager(database), LocalAssets(Path(setting('MEDIA_ROOT', str(Path(database).parent / 'media'))))


def local_time(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M')


def select_project(project):
    st.query_params['video'] = project.id
    st.session_state.video_select_next = project.id
    st.rerun()


def progress_widget():
    bar = st.progress(0.0, text='準備處理…')
    def update(label, fraction):
        bar.progress(min(1.0, max(0.0, float(fraction))), text=label)
    return update


def upload_section(s, manager, assets):
    with st.expander('建立新剪輯專案｜選擇腳本並上傳影片', expanded=not manager.list()):
        scripts = s.repo.list_projects()
        if not scripts:
            st.info('請先在「腳本編輯」儲存一份腳本，再上傳本次拍攝的影片。')
            return
        script = st.selectbox('本次拍攝使用的腳本', scripts, format_func=lambda p: p.title, key='video_script')
        st.caption(f'使用 V{script.versions[-1].number} 的腳本快照，日後修改原腳本不會影響此剪輯專案。')
        uploaded = st.file_uploader('上傳手機拍攝的完整影片（MP4／MOV，最多500 MB、15分鐘）', type=['mp4', 'mov'], key='video_upload')
        if uploaded and st.button('建立剪輯專案', type='primary'):
            progress = progress_widget()
            with st.spinner('正在檢查完整影片，較大的檔案需要一些時間…'):
                uploaded.seek(0)
                project = create_project(script, uploaded, uploaded.name, assets, manager, progress)
            select_project(project)


def backup_section(manager, assets, project):
    with st.expander('專案備份、恢復與暫存管理'):
        st.download_button('下載剪輯專案 JSON', project.model_dump_json(indent=2),
            file_name=project.id + '_剪輯專案.json', mime='application/json')
        st.caption('JSON 包含腳本快照、辨識結果、剪輯建議及全部已確認的版本；影片不在 JSON 內，請另外保存原片。')
        source = assets.source(project)
        if source.exists():
            with source.open('rb') as media:
                st.download_button('下載原始影片備份', media, file_name='原始影片' + project.source_suffix, mime='video/mp4' if project.source_suffix == '.mp4' else 'video/quicktime')
        upload = st.file_uploader('匯入剪輯專案 JSON（建立獨立副本）', type=['json'], key='video_restore')
        if upload and st.button('驗證並恢復剪輯專案'):
            select_project(manager.import_metadata(upload.getvalue()))
        st.caption('只清除暫存音訊與預覽檔，保留原片、已輸出影片及所有已確認時間軸。')
        if st.checkbox('確認清理此專案的暫存檔') and st.button('清理暫存'):
            st.success(f'已清理 {assets.temporary_cleanup(project.id)} 個暫存／預覽檔。')


def analysis_section(s, manager, assets, project):
    st.subheader('三、分析口播內容')
    if not project.media.audio_codec:
        st.warning('這支影片沒有音軌，無法進行語音辨識與停頓分析；仍可人工剪輯，輸出會加入無聲音軌。')
        return
    with st.expander('分析設定'):
        min_pause = st.number_input('列為過長停頓的秒數', min_value=.5, max_value=10.0, value=project.settings.min_pause, step=.1)
        retain = st.number_input('縮短後保留的呼吸空間（秒）', min_value=.3, max_value=1.5, value=project.settings.retain_pause, step=.1)
        threshold = st.slider('靜音判斷門檻（dB）', -60, -15, value=project.settings.noise_db)
        st.caption('低於0.5秒的停頓不列入建議。只有不碰到辨識語音的長停頓會預先勾選，仍需保存確認。')
    semantic = st.checkbox('加入 Gemini 語意分析（將本次腳本快照與辨識文字傳送至 Gemini，影片與音訊留在本機）', value=bool(s.provider.api_key), disabled=not bool(s.provider.api_key))
    rerun = st.checkbox('重新分析剪輯建議（沿用已完成的同模型語音辨識）', value=False)
    if st.button('開始分析', type='primary'):
        settings = AnalysisSettings(min_pause=min_pause, retain_pause=retain, noise_db=threshold)
        provider = FasterWhisperProvider(setting('WHISPER_MODEL', 'small'), Path(setting('WHISPER_MODEL_DIR', str(ROOT / 'models/whisper'))))
        with st.spinner('分析中；首次下載辨識模型可能較久，請保持頁面開啟…'):
            analyze(project, manager, assets, provider, s.provider if semantic else None, settings, force=rerun, progress=progress_widget())
        st.rerun()
    if project.analysis_note:
        st.info(project.analysis_note)
    if project.transcript:
        with st.expander('查看逐字辨識與腳本比對', expanded=False):
            st.caption('時間來自本機音訊對齊，仍有辨識誤差，請聽剪輯點；本版不提供未校準的信心分數。')
            st.dataframe([{'開始（秒）': s.start, '結束（秒）': s.end, '實際口播': s.text, '信心': s.confidence} for s in project.transcript.segments], hide_index=True, use_container_width=True)
            labels = {'matched': '文字相近', 'paraphrase': '合理口語改寫', 'needs_review': '待確認', 'missing': '可能漏講／需重拍'}
            for match in project.matches:
                st.write(f'{match.script_index + 1}. {match.script_text}')
                st.caption(labels[match.status] + '：' + match.reason)


def decisions_editor(project, manager, assets):
    st.subheader('四、確認剪輯與人工調整')
    latest = project.timelines[-1]
    source = st.radio('編輯依據', ['目前已確認時間軸', '最新分析建議'], index=1 if len(project.timelines) == 1 and project.suggestions else 0, horizontal=True)
    decisions = project.suggestions if source == '最新分析建議' else latest.decisions
    st.caption('「刪除／縮短」未勾選的片段會保留。涉及語音或手動修改時間的片段，需同時勾選「人工確認」。按保存後才會建立新版本。')
    edited = []
    if decisions:
        with st.expander('逐段查看原因與試聽'):
            item = st.selectbox('選擇要確認的片段', decisions, format_func=lambda d: f'{d.start:.2f}～{d.end:.2f}秒｜{d.reason[:28]}', key=f'listen_{project.id}_{source}')
            st.write(item.reason)
            st.video(str(assets.source(project)), start_time=max(0, item.start - .3), end_time=min(project.media.duration, item.end + .3), width=360)
        rows = [{'片段ID': d.id, '刪除／縮短': d.selected, '人工確認': d.confirmed, '開始（秒）': d.start,
                 '結束（秒）': d.end, '判斷': {'silence': '過長停頓', 'repetition': '疑似重複', 'retake': '疑似重講', 'semantic': '語意待確認', 'manual': '人工剪輯'}[d.kind],
                 '原因': d.reason} for d in decisions]
        data = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
            disabled=['片段ID', '判斷', '原因'], key=f'decisions_{project.id}_{project.revision}_{source}',
            column_config={'片段ID': None, '開始（秒）': st.column_config.NumberColumn(min_value=0.0, max_value=project.media.duration, step=.01, format='%.2f'),
                           '結束（秒）': st.column_config.NumberColumn(min_value=0.0, max_value=project.media.duration, step=.01, format='%.2f')})
        for original, row in zip(decisions, data.to_dict('records')):
            item = original.model_copy(deep=True)
            changed = (row['開始（秒）'], row['結束（秒）']) != (item.start, item.end)
            item.start, item.end = row['開始（秒）'], row['結束（秒）']
            item.selected, item.confirmed = bool(row['刪除／縮短']), bool(row['人工確認'])
            if changed:
                item.requires_review = True
                item.reason += '（人工調整時間）'
            edited.append(Decision.model_validate(item.model_dump()))
        if st.button('確認並保存這份剪輯時間軸', type='primary'):
            confirm_timeline(project, manager, edited)
            st.rerun()
    else:
        st.info('目前完整保留原片；可開始分析或手動新增一段剪輯。')
    with st.expander('手動新增刪除片段'):
        with st.form('manual_cut_' + project.id):
            start = st.number_input('手動刪除開始（秒）', min_value=0.0, max_value=project.media.duration, value=0.0, step=.01)
            end = st.number_input('手動刪除結束（秒）', min_value=0.0, max_value=project.media.duration, value=min(1.0, project.media.duration), step=.01)
            confirmed = st.checkbox('我已聽過這一段，確認刪除')
            if st.form_submit_button('加入並保存新版本'):
                if not confirmed:
                    raise VideoError('請先勾選「我已聽過這一段，確認刪除」。')
                manual = Decision(start=start, end=end, kind='manual', reason='使用者手動確認刪除', selected=True, confirmed=True)
                confirm_timeline(project, manager, [*latest.decisions, manual])
                st.rerun()
    with st.expander('已保存的剪輯版本與保留片段'):
        chosen = st.selectbox('查看剪輯版本', project.timelines, format_func=lambda t: f'V{t.number} · {t.note}', index=len(project.timelines) - 1)
        st.dataframe([{'保留開始（秒）': t.start, '保留結束（秒）': t.end} for t in chosen.keep_segments], hide_index=True)
        st.caption(' × '.join([f'{sum(k.end-k.start for k in chosen.keep_segments):.2f}秒', f'{len(chosen.keep_segments)}個保留片段']))
        if st.button('恢復這個剪輯版本（保留全部歷史）'):
            restore_timeline(project, manager, chosen.number)
            st.rerun()


def export_section(manager, assets, project):
    st.subheader('六、預覽與輸出 MP4')
    timeline = project.timelines[-1]
    captioned = bool(project.subtitles and project.subtitles.enabled)
    signature = delivery_signature(project)
    st.caption('目前輸出：' + ('帶字幕 MP4（已保存的字幕與樣式）' if captioned else '無字幕 MP4'))
    try:
        options = {'subtitles': delivery_cues(project), 'subtitle_style': project.subtitles.style} if captioned else {}
    except VideoError as exc:
        st.info(str(exc) + ' 也可先關閉字幕，輸出原本的粗剪影片。')
        return
    st.caption(f'目前使用已保存的 V{timeline.number}。表格中尚未保存的調整不會加入預覽或輸出。')
    preview_key = f'preview-{timeline.number}-{signature}.mp4' if captioned else f'preview-{timeline.number}.mp4'
    preview = assets.path(project.id, preview_key)
    if st.button('產生粗剪預覽'):
        if not preview.exists():
            with st.spinner('正在產生較小的預覽影片…'):
                render_video(assets.source(project), preview, timeline, project.media, project.source_sha256, preview=True, progress=progress_widget(), **options)
                from core.subtitles.burn import prune_previews
                prune_previews(assets, project.id, preserve=preview)
        st.rerun()
    if preview.exists():
        st.video(str(preview), width=360)
    confirmed = st.checkbox('我已確認目前已保存的剪輯內容，準備輸出 MP4', key=f'export_confirm_{project.id}_{timeline.number}')
    if st.button('輸出 MP4', type='primary', disabled=not confirmed):
        key = f'output-v{timeline.number}-{uuid4().hex[:8]}.mp4'
        with st.spinner('正在輸出原比例影片，請保持頁面開啟…'):
            render_video(assets.source(project), assets.path(project.id, key), timeline, project.media, project.source_sha256, progress=progress_widget(), **options)
        updated = project.model_copy(deep=True)
        updated.output_key, updated.output_timeline, updated.export_status = key, timeline.number, '已輸出'
        updated.output_signature = signature
        manager.save(updated)
        st.rerun()
    if (project.output_key and project.output_timeline == timeline.number and
            (project.output_signature == signature or (not project.output_signature and not captioned))):
        output = assets.path(project.id, project.output_key)
        if output.exists():
            st.success('MP4 已輸出，可預覽及下載。')
            st.video(str(output), width=360)
            with output.open('rb') as video:
                st.download_button('下載 MP4', video, file_name=filename(project.title), mime='video/mp4')


def render(s):
    st.header('AI 影片粗剪')
    st.write('選腳本 → 上傳影片 → 分析 → 確認剪輯 → 確認字幕 → 輸出')
    st.info('原片保持不變。重講與口誤預設保留，請逐項確認；時間來自音訊分析，仍需聽過剪輯點。')
    st.caption('目前為本機處理：每支最多500 MB／15分鐘。雲端本機檔案不保證永久保存，請同時備份專案 JSON 與原片；大型影片建議在這台電腦處理。')
    try:
        binary('ffmpeg')
        binary('ffprobe')
    except VideoError as exc:
        st.warning(str(exc))
        st.code('.\\.venv\\Scripts\\python.exe tools/install_ffmpeg.py', language='powershell')
        return
    manager, assets = resources(s)
    upload_section(s, manager, assets)
    projects = manager.list()
    if not projects:
        with st.expander('從備份恢復剪輯專案'):
            upload = st.file_uploader('剪輯專案 JSON', type=['json'], key='restore_without_project')
            if upload and st.button('恢復剪輯專案'):
                select_project(manager.import_metadata(upload.getvalue()))
        return
    ids = [p.id for p in projects]
    current = st.query_params.get('video')
    if st.session_state.get('video_select_next') in ids:
        st.session_state.video_project_select = st.session_state.pop('video_select_next')
    selected = st.selectbox('開啟剪輯專案', ids, index=ids.index(current) if current in ids else 0,
        format_func=lambda pid: next(p.title + ' · ' + local_time(p.created_at) for p in projects if p.id == pid), key='video_project_select')
    if selected != current:
        st.query_params['video'] = selected
    project = manager.get(selected)
    st.subheader('本次影片')
    st.write(f'**{project.title}** · 原始檔名：{project.original_name}')
    st.caption(f'{project.media.duration:.2f}秒 · {project.media.display_width} × {project.media.display_height} · {project.media.size / 1024**2:.1f} MB · {project.source_suffix.upper()[1:]} · 腳本 V{project.script_version}')
    source = assets.source(project)
    backup_section(manager, assets, project)
    if not source.exists():
        st.warning('專案時間軸已恢復，但需要重新提供原始影片；系統會比對檔案指紋。')
        upload = st.file_uploader('重新連結原始影片', type=['mp4', 'mov'], key='reattach')
        if upload and st.button('驗證並連結原片'):
            upload.seek(0)
            reattach_source(project, upload, upload.name, assets)
            st.rerun()
        return
    with st.expander('原始影片與片段試聽', expanded=True):
        start = st.number_input('從原片第幾秒開始預覽', min_value=0.0, max_value=max(0.0, project.media.duration - .01), value=0.0, step=.1)
        st.video(str(source), start_time=start, width=360)
    analysis_section(s, manager, assets, project)
    decisions_editor(project, manager, assets)
    render_subtitles(project, manager, assets)
    export_section(manager, assets, project)

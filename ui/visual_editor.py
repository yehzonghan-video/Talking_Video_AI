"""Native JS custom component. Only explicit commit actions trigger Python."""
from functools import lru_cache
from pathlib import Path
import streamlit as st
from pydantic import ValidationError
from core.editor.service import document, save_document
from core.subtitles.mapping import map_captions
from core.subtitles.service import delivery_signature
from core.subtitles.correction import prepare_track
from core.video.errors import VideoError
from core.storage.project_manager import StorageError
from core.video.export_service import export_mp4, export_srt
from core.video.timeline import filename
from ui.media_reference import video_reference

FRONTEND = Path(__file__).parent / 'frontend'


@lru_cache(maxsize=4)
def component_renderer(registry, asset_version):
    import streamlit.components.v2 as components
    javascript = (FRONTEND / 'editor_model.mjs').read_text(encoding='utf-8') + '\n' + (FRONTEND / 'editor.js').read_text(encoding='utf-8')
    return components.component('talking_video_visual_editor', css=(FRONTEND / 'editor.css').read_text(encoding='utf-8'), js=javascript)


def mount(data, key):
    from streamlit import runtime
    registry = runtime.get_instance().bidi_component_registry
    version = tuple((FRONTEND / name).stat().st_mtime_ns for name in ('editor_model.mjs', 'editor.js', 'editor.css'))
    return component_renderer(registry, version)(data=data, key=key, height='content', on_commit_change=lambda: None)


def render(project, manager, assets):
    st.subheader('影片與字幕編輯器')
    st.caption(f'字幕文字採用本專案已保存的 V{project.script_version} 逐字稿；人工修字優先，辨識文字只協助對齊時間。')
    if project.subtitles and project.subtitles.unaligned:
        with st.expander(f'{len(project.subtitles.unaligned)} 句逐字稿無法對齊（不影響其他字幕輸出）'):
            st.caption('這些句子目前不顯示字幕；可略過，或以剪輯後秒數手動指定時間。')
            index = st.selectbox('無法對齊的逐字稿', range(len(project.subtitles.unaligned)),
                format_func=lambda i: project.subtitles.unaligned[i], key='unaligned_' + project.id)
            start = st.number_input('手動字幕開始（剪輯後秒數）', min_value=0., value=0., step=.1)
            end = st.number_input('手動字幕結束（剪輯後秒數）', min_value=0., value=1., step=.1)
            from core.subtitles.service import resolve_unaligned
            if st.button('不顯示這一句'):
                resolve_unaligned(project, manager, index)
                st.rerun()
            if st.button('套用手動時間'):
                resolve_unaligned(project, manager, index, start, end)
                st.rerun()
    data = document(project)
    data['media_url'] = video_reference(assets.source(project), project.id)
    data['raw_segments'] = [{'spans': [{'start': s.start, 'end': s.end}], 'text': s.text}
                            for s in project.transcript.segments] if project.transcript else []
    data['original_cues'] = [c.model_dump() for c in (project.subtitles.original_cues or project.subtitles.cues)] if project.subtitles else []
    if project.subtitles:
        track = prepare_track(project.subtitles, project.script_snapshot)
        data['layout_hints'] = [{**c.model_dump(), 'base_id': c.id.split(':')[0], 'plain': ''.join(c.text.split())}
                                for c in map_captions(track, project.timelines[-1])]
    else:
        data['layout_hints'] = []
    outcomes = st.session_state.setdefault('_visual_editor_outcomes', {})
    data['outcome'] = outcomes.get(project.id)
    data['output_url'] = ''
    if project.output_key and project.output_signature == delivery_signature(project):
        output = assets.path(project.id, project.output_key)
        if output.exists():
            data['output_url'] = video_reference(output, project.id + '-output')
    result = mount(data, key='visual_editor_' + project.id)
    event = result.get('commit') if result else None
    if event:
        handled = st.session_state.setdefault('_visual_editor_handled', [])
        request = event.get('request') if isinstance(event, dict) else None
        operation = request.get('operation_id') if isinstance(request, dict) else None
        if operation not in handled:
            saved = None
            try:
                if not isinstance(event, dict) or set(event) != {'action', 'request'} or event['action'] not in ('save', 'export', 'srt'):
                    raise VideoError('編輯操作格式無效。')
                saved = save_document(project.id, manager, event['request'])
                outcome = {'operation_id': operation, 'message': '剪輯、字幕與樣式已一併儲存。'}
                if event['action'] == 'export':
                    with st.spinner('編輯已保存，正在輸出 MP4…'):
                        saved = export_mp4(saved, manager, assets)
                    outcome['message'] = 'MP4 已輸出，可在下方播放及下載。'
                elif event['action'] == 'srt':
                    outcome['srt'] = export_srt(saved)
                outcomes[project.id] = outcome
            except (ValidationError, TypeError, ValueError):
                outcomes[project.id] = {'operation_id': operation, 'error': '編輯資料格式或時間不正確，請核對後重試；瀏覽器草稿仍保留。'}
            except (VideoError, StorageError) as exc:
                prefix = '編輯已保存，但輸出未完成。' if saved is not None else ''
                outcomes[project.id] = {'operation_id': operation, 'error': prefix + str(exc), 'conflict': isinstance(exc, StorageError)}
            handled.append(operation)
            del handled[:-100]
            st.rerun()
    if (project.output_key and project.output_signature == delivery_signature(project)
            and assets.path(project.id, project.output_key).exists()):
        output = assets.path(project.id, project.output_key)
        st.success('目前已保存版本的 MP4 已完成。')
        from ui.downloads import mp4_download
        mp4_download(project, assets)
    elif project.output_key and project.output_signature == delivery_signature(project):
        from core.video.diagnostics import record
        record('download_unavailable', exists=False, session_reference=False)
        st.warning('已輸出的 MP4 檔案目前不存在，可能因雲端主機重建而遺失；請保留原片並重新輸出。')

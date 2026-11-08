"""Selective media analysis with operator permission, local decoding and byte/time caps."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import timedelta

import requests
from .engine_store import digest
from .http import public_url
from .model import parse_time
from .providers import ProviderDisabled


def permitted(url, records, now):
    for r in records:
        reviewed=parse_time(r.get('reviewed_at'))
        if (r.get('asset_url')==url and r.get('analysis_permitted') is True and not r.get('revoked') and
            isinstance(r.get('evidence_url'),str) and r['evidence_url'].startswith('https://') and
            reviewed and now-timedelta(days=365)<=reviewed<=now):return True
    return False


def transcribe(path, duration, ledger, request=requests.post):
    token=os.environ.get('OPENAI_API_KEY')
    if not token:raise ProviderDisabled('openai_not_configured')
    if not 0<duration<=180:raise ProviderDisabled('audio_duration_limit')
    audio=Path(path).read_bytes()
    if len(audio)>8_000_000:raise ProviderDisabled('audio_byte_limit')
    inputs={'model':'gpt-transcribe','content_hash':digest(audio.hex()),'language':'vi'}
    # Reserve the full three minutes, including rounding, regardless of length.
    row,created=ledger.reserve('openai','transcribe',inputs,14000)
    if not created:
        if row['status']=='complete' and row['result']:return row['result']['text']
        raise ProviderDisabled('transcription_already_reserved')
    ledger.update(row['id'],'unknown')
    try:
        response=request('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+token},
            data={'model':'gpt-transcribe','language':'vi'},files={'file':('audio.wav',audio,'audio/wav')},
            timeout=(10,120),allow_redirects=False)
        if response.status_code!=200:raise ProviderDisabled(f'provider_http_{response.status_code}')
        text=response.json().get('text')
        if not isinstance(text,str):raise ProviderDisabled('invalid_transcription')
    except (requests.RequestException,ValueError):raise ProviderDisabled('transcription_unavailable') from None
    ledger.update(row['id'],'complete',result={'text':text[:18000]},usage={'seconds':duration})
    return text[:18000]


def analyze_media(url,platform,records,now,ledger):
    if platform=='youtube' or not permitted(url,records,now):raise ProviderDisabled('media_analysis_permission_required')
    # Never hand a remote URL to ffmpeg. No redirects, bounded download, temporary
    # storage, no playback/publication and no external protocol from a playlist.
    from .multimodal import image_input
    from PIL import Image
    import base64,io
    public_url(url)
    with tempfile.TemporaryDirectory(prefix='lo-media-') as tmp:
        source=Path(tmp)/'source';size=0
        with requests.get(url,stream=True,allow_redirects=False,timeout=(10,30)) as response:
            if response.status_code!=200:raise ProviderDisabled('media_unavailable')
            with source.open('wb') as out:
                for block in response.iter_content(65536):
                    size+=len(block)
                    if size>20_000_000:raise ProviderDisabled('media_byte_limit')
                    out.write(block)
        try:
            result=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration',
                '-of','json',str(source)],capture_output=True,timeout=15,check=True)
            duration=float(json.loads(result.stdout)['format']['duration'])
            if not 0<duration<=180:raise ProviderDisabled('media_duration_limit')
            audio=Path(tmp)/'audio.wav'
            subprocess.run(['ffmpeg','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-vn','-ac','1','-ar','16000',
                '-t','180',str(audio)],capture_output=True,timeout=30,check=True)
            transcript=transcribe(audio,duration,ledger)
            subprocess.run(['ffmpeg','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-vf',
                f'fps=1/{max(1,duration/12)},scale=1024:1024:force_original_aspect_ratio=decrease',
                '-frames:v','12',str(Path(tmp)/'frame-%02d.jpg')],capture_output=True,timeout=30,check=True)
            frames=[]
            for n,path in enumerate(sorted(Path(tmp).glob('frame-*.jpg'))[:12]):
                frames.append({'id':f'frame_{n}','data_url':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode(),
                               'time_seconds':round(n*max(1,duration/12),3)})
            return {'transcript':transcript,'frames':frames,'duration':duration,'coverage':'sampled_frames_full_audio'}
        except (OSError,subprocess.SubprocessError,ValueError,KeyError):
            raise ProviderDisabled('media_decode_unavailable') from None

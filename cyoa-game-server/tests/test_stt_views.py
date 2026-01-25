"""
Tests for stt_views.py - Speech-to-Text API

Uses real audio file (jfk.wav from whisper.cpp) for testing.
"""
import pytest
import json
import uuid
from unittest.mock import patch, MagicMock
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from game.models import STTRecording
from game.stt_views import convert_to_wav, transcribe_with_whisper_api
from tests.conftest import STTRecordingFactory

# Path to test audio
TEST_AUDIO_FILE = Path(__file__).parent / 'fixtures' / 'jfk.wav'
JFK_TRANSCRIPT = "And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country."


@pytest.mark.unit
class TestConvertToWav:
    @patch('subprocess.run')
    def test_calls_ffmpeg_correctly(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = convert_to_wav('/in.webm', '/out.wav')
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert '-ar' in call_args and '16000' in call_args


@pytest.mark.unit  
class TestTranscribeWithWhisperAPI:
    @patch('requests.post')
    def test_successful_transcription(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'text': JFK_TRANSCRIPT}
        )
        transcript, error = transcribe_with_whisper_api(str(TEST_AUDIO_FILE))
        assert transcript == JFK_TRANSCRIPT
        assert error is None


@pytest.mark.django_db
class TestSTTUploadAPI:
    def test_upload_requires_audio_file(self, client):
        response = client.post('/api/stt/upload')
        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'audio' in data['error'].lower()
    
    def test_upload_accepts_wav(self, client, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        with open(TEST_AUDIO_FILE, 'rb') as f:
            audio_data = f.read()
        uploaded_file = SimpleUploadedFile('jfk.wav', audio_data, content_type='audio/wav')
        response = client.post('/api/stt/upload', {'audio': uploaded_file})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'recording_id' in data
        assert data['status'] == 'uploaded'
        uuid.UUID(data['recording_id'])


@pytest.mark.django_db
class TestSTTTranscribeAPI:
    def test_transcribe_requires_recording_id(self, client):
        response = client.post('/api/stt/transcribe', data=json.dumps({}), content_type='application/json')
        assert response.status_code == 400
    
    @patch('game.stt_views.convert_to_wav')
    @patch('game.stt_views.transcribe_with_whisper_api')
    def test_transcribe_success(self, mock_whisper, mock_convert, client, db, tmp_path):
        """Test transcription with proper file setup."""
        # Setup test media directory
        audio_dir = tmp_path / 'stt_recordings'
        audio_dir.mkdir()
        
        # Copy the test audio file to the expected location
        audio_file = audio_dir / 'test.wav'
        with open(TEST_AUDIO_FILE, 'rb') as src:
            with open(audio_file, 'wb') as dst:
                dst.write(src.read())
        
        # Create recording pointing to the actual file
        recording = STTRecordingFactory(file_path='stt_recordings/test.wav', status='uploaded')
        
        # Mock the conversion and transcription
        mock_convert.return_value = True
        mock_whisper.return_value = (JFK_TRANSCRIPT, None)
        
        # Patch MEDIA_ROOT to use tmp_path
        with patch('game.stt_views.MEDIA_ROOT', tmp_path):
            response = client.post('/api/stt/transcribe', data=json.dumps({'recording_id': str(recording.id)}), content_type='application/json')
        
        # Assertions
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['status'] == 'transcribed'
        assert data['transcript'] == JFK_TRANSCRIPT


@pytest.mark.django_db
class TestSTTRecordingStatusAPI:
    def test_get_status_nonexistent(self, client, db):
        response = client.get(f'/api/stt/recording/{uuid.uuid4()}')
        assert response.status_code == 404
    
    def test_get_status_transcribed(self, client, db):
        recording = STTRecordingFactory(status='transcribed', transcript_text=JFK_TRANSCRIPT)
        response = client.get(f'/api/stt/recording/{recording.id}')
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['status'] == 'transcribed'
        assert data['transcript'] == JFK_TRANSCRIPT


@pytest.mark.django_db
class TestSTTDiscardAPI:
    def test_discard_marks_as_deleted(self, client, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        audio_dir = tmp_path / 'stt_recordings'
        audio_dir.mkdir()
        audio_file = audio_dir / 'test.wav'
        with open(TEST_AUDIO_FILE, 'rb') as src:
            with open(audio_file, 'wb') as dst:
                dst.write(src.read())
        recording = STTRecordingFactory(file_path='stt_recordings/test.wav', status='uploaded')
        response = client.post('/api/stt/discard', data=json.dumps({'recording_id': str(recording.id)}), content_type='application/json')
        assert response.status_code == 200
        recording.refresh_from_db()
        assert recording.status == 'deleted'


@pytest.mark.django_db
@pytest.mark.integration
class TestFullSTTFlow:
    @patch('game.stt_views.convert_to_wav')
    @patch('game.stt_views.transcribe_with_whisper_api')
    def test_complete_workflow(self, mock_transcribe, mock_convert, client, db, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        mock_convert.return_value = True
        mock_transcribe.return_value = (JFK_TRANSCRIPT, None)
        
        # Upload
        with open(TEST_AUDIO_FILE, 'rb') as f:
            audio_data = f.read()
        uploaded_file = SimpleUploadedFile('jfk.wav', audio_data, content_type='audio/wav')
        upload_resp = client.post('/api/stt/upload', {'audio': uploaded_file})
        recording_id = json.loads(upload_resp.content)['recording_id']
        
        # Transcribe
        trans_resp = client.post('/api/stt/transcribe', data=json.dumps({'recording_id': recording_id}), content_type='application/json')
        assert json.loads(trans_resp.content)['transcript'] == JFK_TRANSCRIPT
        
        # Check status
        status_resp = client.get(f'/api/stt/recording/{recording_id}')
        assert json.loads(status_resp.content)['status'] == 'transcribed'
        
        # Discard
        discard_resp = client.post('/api/stt/discard', data=json.dumps({'recording_id': recording_id}), content_type='application/json')
        assert discard_resp.status_code == 200

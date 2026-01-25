"""
Speech-to-Text API views for audio recording and transcription.
"""
import os
import uuid
import json
import subprocess
import tempfile
import logging
import requests
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import STTRecording

logger = logging.getLogger(__name__)

# Configuration for whisper.cpp endpoint
WHISPER_API_URL = os.environ.get('WHISPER_API_URL', 'http://host.docker.internal:10300/v1/audio/transcriptions')
WHISPER_TIMEOUT = int(os.environ.get('WHISPER_TIMEOUT', '300'))  # 5 minute default timeout

# Media root for storing recordings
MEDIA_ROOT = getattr(settings, 'MEDIA_ROOT', settings.BASE_DIR / 'media')
STT_RECORDINGS_DIR = Path(MEDIA_ROOT) / 'stt_recordings'


def ensure_stt_dir():
    """Ensure the STT recordings directory exists."""
    STT_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def convert_to_wav(input_path: str, output_path: str) -> bool:
    """
    Convert audio file to 16kHz mono WAV using ffmpeg.
    Returns True on success, False on failure.
    """
    try:
        cmd = [
            'ffmpeg', '-y',  # Overwrite output
            '-i', input_path,
            '-ar', '16000',  # 16kHz sample rate
            '-ac', '1',      # Mono
            '-f', 'wav',
            output_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120  # 2 minute timeout for conversion
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg conversion failed: {result.stderr.decode()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg conversion timed out")
        return False
    except Exception as e:
        logger.error(f"ffmpeg conversion error: {e}")
        return False


def transcribe_with_whisper_api(wav_path: str) -> tuple[str | None, str | None]:
    """
    Transcribe audio using whisper.cpp OpenAI-compatible API.
    Returns (transcript, error_message).
    """
    try:
        with open(wav_path, 'rb') as audio_file:
            files = {
                'file': ('audio.wav', audio_file, 'audio/wav'),
            }
            data = {
                'model': 'whisper-1',  # Ignored by whisper.cpp but required by API
                'response_format': 'json',
            }
            
            response = requests.post(
                WHISPER_API_URL,
                files=files,
                data=data,
                timeout=WHISPER_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                transcript = result.get('text', '').strip()
                # Remove line breaks and collapse multiple spaces to single space
                # This ensures the transcript is a continuous block of text
                import re
                transcript = re.sub(r'\s+', ' ', transcript).strip()

                # Remove common Whisper hallucinations at the end of the text
                # These often appear when the audio ends with silence or noise
                hallucination_pattern = r'(?i)(?:^|\s+)(?:(?:Thanks?|Thank you)(?:\s+for\s+(?:watching|listening|playing))?|Okay|Ok|Bye|Yes|Subtitles\s+by\s+.*?)\W*$'

                while True:
                    new_transcript = re.sub(hallucination_pattern, '', transcript).strip()
                    if new_transcript == transcript:
                        break
                    transcript = new_transcript

                return transcript, None
            else:
                error_msg = f"Whisper API returned {response.status_code}: {response.text}"
                logger.error(error_msg)
                return None, error_msg
                
    except requests.Timeout:
        error_msg = "Whisper API request timed out"
        logger.error(error_msg)
        return None, error_msg
    except requests.ConnectionError as e:
        error_msg = f"Could not connect to Whisper API: {e}"
        logger.error(error_msg)
        return None, error_msg
    except Exception as e:
        error_msg = f"Whisper API error: {e}"
        logger.error(error_msg)
        return None, error_msg


@csrf_exempt
@require_http_methods(["POST"])
def stt_upload(request):
    """
    Upload audio file for transcription.
    
    POST /api/stt/upload
    Content-Type: multipart/form-data
    
    Form fields:
    - audio: The audio file (required)
    - recording_id: Optional client-provided UUID for idempotency
    
    Returns: { recording_id: string }
    """
    try:
        ensure_stt_dir()
        
        if 'audio' not in request.FILES:
            return JsonResponse({'error': 'No audio file provided'}, status=400)
        
        audio_file = request.FILES['audio']
        
        # Use provided recording_id or generate new one
        recording_id = request.POST.get('recording_id')
        if recording_id:
            try:
                recording_id = uuid.UUID(recording_id)
            except ValueError:
                return JsonResponse({'error': 'Invalid recording_id format'}, status=400)
        else:
            recording_id = uuid.uuid4()
        
        # Check if recording already exists (idempotency)
        existing = STTRecording.objects.filter(id=recording_id).first()
        if existing and existing.status != 'deleted':
            return JsonResponse({
                'recording_id': str(existing.id),
                'status': existing.status,
                'message': 'Recording already exists'
            })
        
        # Determine file extension from mime type
        mime_type = audio_file.content_type or 'audio/webm'
        ext_map = {
            'audio/webm': '.webm',
            'audio/mp4': '.m4a',
            'audio/mpeg': '.mp3',
            'audio/wav': '.wav',
            'audio/ogg': '.ogg',
        }
        ext = ext_map.get(mime_type, '.webm')
        
        # Save the file
        filename = f"{recording_id}{ext}"
        file_path = STT_RECORDINGS_DIR / filename
        
        with open(file_path, 'wb+') as dest:
            for chunk in audio_file.chunks():
                dest.write(chunk)
        
        # Create database record
        recording = STTRecording.objects.create(
            id=recording_id,
            file_path=str(file_path.relative_to(MEDIA_ROOT)),
            mime_type=mime_type,
            status='uploaded'
        )
        
        logger.info(f"Audio uploaded: {recording_id}, size: {audio_file.size} bytes")
        
        return JsonResponse({
            'recording_id': str(recording.id),
            'status': recording.status
        })
        
    except Exception as e:
        logger.exception("Error in stt_upload")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def stt_transcribe(request):
    """
    Transcribe a previously uploaded recording.
    
    POST /api/stt/transcribe
    Content-Type: application/json
    
    Body: { recording_id: string }
    
    Returns: { transcript: string, status: string }
    """
    try:
        body = json.loads(request.body)
        recording_id = body.get('recording_id')
        
        if not recording_id:
            return JsonResponse({'error': 'recording_id required'}, status=400)
        
        try:
            recording_uuid = uuid.UUID(recording_id)
        except ValueError:
            return JsonResponse({'error': 'Invalid recording_id format'}, status=400)
        
        # Get the recording
        try:
            recording = STTRecording.objects.get(id=recording_uuid)
        except STTRecording.DoesNotExist:
            return JsonResponse({'error': 'Recording not found'}, status=404)
        
        if recording.status == 'deleted':
            return JsonResponse({'error': 'Recording has been deleted'}, status=404)
        
        # If already transcribed, return the result
        if recording.status == 'transcribed' and recording.transcript_text:
            return JsonResponse({
                'recording_id': str(recording.id),
                'status': 'transcribed',
                'transcript': recording.transcript_text
            })
        
        # Mark as processing
        recording.status = 'processing'
        recording.error_text = None
        recording.save()
        
        # Get the full path to the audio file
        audio_path = Path(MEDIA_ROOT) / recording.file_path
        
        if not audio_path.exists():
            recording.status = 'failed'
            recording.error_text = 'Audio file not found on server'
            recording.save()
            return JsonResponse({
                'recording_id': str(recording.id),
                'status': 'failed',
                'error': recording.error_text
            }, status=404)
        
        # Convert to WAV for Whisper
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
            wav_path = wav_file.name
        
        try:
            if not convert_to_wav(str(audio_path), wav_path):
                recording.status = 'failed'
                recording.error_text = 'Failed to convert audio to WAV format'
                recording.save()
                return JsonResponse({
                    'recording_id': str(recording.id),
                    'status': 'failed',
                    'error': recording.error_text
                }, status=500)
            
            # Transcribe with Whisper
            transcript, error = transcribe_with_whisper_api(wav_path)
            
            if error:
                recording.status = 'failed'
                recording.error_text = error
                recording.save()
                return JsonResponse({
                    'recording_id': str(recording.id),
                    'status': 'failed',
                    'error': error
                }, status=500)
            
            # Success!
            recording.status = 'transcribed'
            recording.transcript_text = transcript
            recording.error_text = None
            recording.save()
            
            logger.info(f"Transcription complete for {recording_id}: {len(transcript)} chars")
            
            return JsonResponse({
                'recording_id': str(recording.id),
                'status': 'transcribed',
                'transcript': transcript
            })
            
        finally:
            # Clean up temp WAV file
            if os.path.exists(wav_path):
                os.remove(wav_path)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    except Exception as e:
        logger.exception("Error in stt_transcribe")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def stt_recording_status(request, recording_id):
    """
    Get the status of a recording and its transcript if available.
    
    GET /api/stt/recording/<recording_id>
    
    Returns: { recording_id, status, transcript?, error? }
    """
    try:
        try:
            recording_uuid = uuid.UUID(recording_id)
        except ValueError:
            return JsonResponse({'error': 'Invalid recording_id format'}, status=400)
        
        try:
            recording = STTRecording.objects.get(id=recording_uuid)
        except STTRecording.DoesNotExist:
            return JsonResponse({'error': 'Recording not found'}, status=404)
        
        if recording.status == 'deleted':
            return JsonResponse({'error': 'Recording has been deleted'}, status=404)
        
        response_data = {
            'recording_id': str(recording.id),
            'status': recording.status,
            'created_at': recording.created_at.isoformat(),
        }
        
        if recording.transcript_text:
            response_data['transcript'] = recording.transcript_text
        
        if recording.error_text:
            response_data['error'] = recording.error_text
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.exception("Error in stt_recording_status")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def stt_discard(request):
    """
    Discard a recording and delete associated files.
    
    POST /api/stt/discard
    Content-Type: application/json
    
    Body: { recording_id: string }
    
    Returns: { success: boolean }
    """
    try:
        body = json.loads(request.body)
        recording_id = body.get('recording_id')
        
        if not recording_id:
            return JsonResponse({'error': 'recording_id required'}, status=400)
        
        try:
            recording_uuid = uuid.UUID(recording_id)
        except ValueError:
            return JsonResponse({'error': 'Invalid recording_id format'}, status=400)
        
        try:
            recording = STTRecording.objects.get(id=recording_uuid)
        except STTRecording.DoesNotExist:
            # Already gone, that's fine
            return JsonResponse({'success': True, 'message': 'Recording not found (already deleted?)'})
        
        # Delete the file
        audio_path = Path(MEDIA_ROOT) / recording.file_path
        if audio_path.exists():
            try:
                audio_path.unlink()
                logger.info(f"Deleted audio file: {audio_path}")
            except Exception as e:
                logger.warning(f"Could not delete audio file {audio_path}: {e}")
        
        # Mark as deleted (or actually delete the DB record)
        recording.status = 'deleted'
        recording.save()
        
        logger.info(f"Recording discarded: {recording_id}")
        
        return JsonResponse({'success': True})
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    except Exception as e:
        logger.exception("Error in stt_discard")
        return JsonResponse({'error': str(e)}, status=500)

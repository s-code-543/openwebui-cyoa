/**
 * CYOA Audio Recorder Module
 * 
 * Handles audio recording, local persistence via IndexedDB, 
 * server upload, and transcription via whisper.cpp.
 * 
 * Features:
 * - No VAD/auto-stop - user controls start/stop
 * - Up to 10 minute recordings
 * - IndexedDB persistence for reliability
 * - Server-side backup after upload
 * - Retry transcription without re-recording
 */

const CYOARecorder = (function() {
  // === Configuration ===
  const DB_NAME = 'cyoa-recordings';
  const DB_VERSION = 1;
  const STORE_NAME = 'recordings';
  const DRAFT_KEY = 'cyoa-draft-text';
  const ACTIVE_RECORDING_KEY = 'cyoa-active-recording-id';
  
  // === State ===
  let db = null;
  let mediaRecorder = null;
  let audioContext = null;
  let analyser = null;
  let mediaStream = null;
  let chunks = [];
  let recordingStartTime = null;
  let timerInterval = null;
  let levelMeterInterval = null;
  let currentRecordingId = null;
  let currentBlob = null;
  let serverRecordingId = null;  // ID from server after upload
  
  // UI State enum
  const UIState = {
    IDLE: 'idle',
    RECORDING: 'recording',
    PROCESSING: 'processing',
    ERROR: 'error',
    SUCCESS: 'success'
  };
  
  let currentState = UIState.IDLE;
  let lastError = null;
  let isCancelled = false;
  
  // Callbacks (set by init)
  let onStateChange = null;
  let onTranscriptReady = null;
  let onLevelUpdate = null;
  let onTimeUpdate = null;
  
  // === IndexedDB Operations ===
  
  async function openDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        db = request.result;
        resolve(db);
      };
      
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
          store.createIndex('createdAt', 'createdAt', { unique: false });
        }
      };
    });
  }
  
  async function saveRecordingToDB(id, blob, mimeType) {
    if (!db) await openDB();
    
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      
      const record = {
        id: id,
        createdAt: new Date().toISOString(),
        mimeType: mimeType,
        blob: blob,
        serverRecordingId: null,  // Will be set after server upload
        status: 'local'  // local, uploaded, transcribed, failed
      };
      
      const request = store.put(record);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        localStorage.setItem(ACTIVE_RECORDING_KEY, id);
        resolve(record);
      };
    });
  }
  
  async function getRecordingFromDB(id) {
    if (!db) await openDB();
    
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      
      const request = store.get(id);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);
    });
  }
  
  async function updateRecordingInDB(id, updates) {
    if (!db) await openDB();
    
    const existing = await getRecordingFromDB(id);
    if (!existing) return null;
    
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      
      const updated = { ...existing, ...updates };
      const request = store.put(updated);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(updated);
    });
  }
  
  async function deleteRecordingFromDB(id) {
    if (!db) await openDB();
    
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      
      const request = store.delete(id);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        if (localStorage.getItem(ACTIVE_RECORDING_KEY) === id) {
          localStorage.removeItem(ACTIVE_RECORDING_KEY);
        }
        resolve();
      };
    });
  }
  
  // === Draft Text Persistence ===
  
  function saveDraftText(text) {
    try {
      localStorage.setItem(DRAFT_KEY, text);
    } catch (e) {
      console.warn('Could not save draft text:', e);
    }
  }
  
  function loadDraftText() {
    try {
      return localStorage.getItem(DRAFT_KEY) || '';
    } catch (e) {
      return '';
    }
  }
  
  function clearDraftText() {
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch (e) {
      // Ignore
    }
  }
  
  // === Audio Recording ===
  
  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }
  
  function getSupportedMimeType() {
    const types = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg;codecs=opus',
    ];
    
    for (const type of types) {
      if (MediaRecorder.isTypeSupported(type)) {
        return type;
      }
    }
    
    // Fallback - let browser decide
    return '';
  }
  
  async function startRecording() {
    try {
      isCancelled = false;
      setState(UIState.RECORDING);
      
      // Request microphone access
      mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      
      // Set up audio analysis for level meter
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      
      const source = audioContext.createMediaStreamSource(mediaStream);
      source.connect(analyser);
      
      // Start level meter updates
      startLevelMeter();
      
      // Set up MediaRecorder
      const mimeType = getSupportedMimeType();
      const options = mimeType ? { mimeType } : {};
      
      mediaRecorder = new MediaRecorder(mediaStream, options);
      chunks = [];
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunks.push(event.data);
        }
      };
      
      mediaRecorder.onstop = async () => {
        if (isCancelled) {
          console.log('Recording cancelled by user');
          stopLevelMeter();
          stopTimer();
          cleanupMediaResources();
          setState(UIState.IDLE);
          discardRecording();
          return;
        }

        // Assemble the recording
        console.log('MediaRecorder stopped, processing...');
        const actualMimeType = mediaRecorder.mimeType || mimeType || 'audio/webm';
        currentBlob = new Blob(chunks, { type: actualMimeType });
        currentRecordingId = generateUUID();
        
        // Save to IndexedDB immediately
        try {
          await saveRecordingToDB(currentRecordingId, currentBlob, actualMimeType);
          console.log('Recording saved to IndexedDB:', currentRecordingId);
        } catch (e) {
          console.error('Failed to save recording to IndexedDB:', e);
        }
        
        // Clean up recording resources
        stopLevelMeter();
        stopTimer();
        cleanupMediaResources();
        
        // Start upload and transcription
        await uploadAndTranscribe();
      };
      
      mediaRecorder.onerror = (event) => {
        console.error('MediaRecorder error:', event.error);
        setError('Recording error: ' + (event.error?.message || 'Unknown error'));
      };
      
      // Start recording - collect data every second for smooth operation
      mediaRecorder.start(1000);
      
      // Start timer
      recordingStartTime = Date.now();
      startTimer();
      
      console.log('Recording started with MIME type:', mediaRecorder.mimeType);
      
    } catch (error) {
      console.error('Failed to start recording:', error);
      cleanupMediaResources();
      
      if (error.name === 'NotAllowedError') {
        setError('Microphone access denied. Please allow microphone access and try again.');
      } else if (error.name === 'NotFoundError') {
        setError('No microphone found. Please connect a microphone and try again.');
      } else {
        setError('Failed to start recording: ' + error.message);
      }
    }
  }
  
  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      setState(UIState.PROCESSING);
    }
  }

  function cancelRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      isCancelled = true;
      mediaRecorder.stop();
    } else {
      discardRecording();
    }
  }
  
  function cleanupMediaResources() {
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }
    
    if (audioContext && audioContext.state !== 'closed') {
      audioContext.close();
      audioContext = null;
    }
    
    analyser = null;
    mediaRecorder = null;
  }
  
  // === Level Meter ===
  
  function startLevelMeter() {
    if (!analyser) return;
    
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    
    levelMeterInterval = setInterval(() => {
      if (!analyser) {
        stopLevelMeter();
        return;
      }
      
      analyser.getByteTimeDomainData(dataArray);
      
      // Calculate RMS level
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const normalized = (dataArray[i] - 128) / 128;
        sum += normalized * normalized;
      }
      const rms = Math.sqrt(sum / dataArray.length);
      
      // Convert to 0-1 range with some amplification
      const level = Math.min(1, rms * 3);
      
      if (onLevelUpdate) {
        onLevelUpdate(level);
      }
    }, 50);  // 20fps for smooth animation
  }
  
  function stopLevelMeter() {
    if (levelMeterInterval) {
      clearInterval(levelMeterInterval);
      levelMeterInterval = null;
    }
    if (onLevelUpdate) {
      onLevelUpdate(0);
    }
  }
  
  // === Timer ===
  
  function startTimer() {
    timerInterval = setInterval(() => {
      if (recordingStartTime && onTimeUpdate) {
        const elapsed = Date.now() - recordingStartTime;
        onTimeUpdate(elapsed);
      }
    }, 100);
  }
  
  function stopTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
  }
  
  function formatTime(ms) {
    const totalSeconds = Math.floor(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }
  
  // === Server Communication ===
  
  async function uploadAndTranscribe() {
    setState(UIState.PROCESSING);
    
    try {
      // Upload to server
      const uploadResult = await uploadToServer();
      
      if (!uploadResult.success) {
        throw new Error(uploadResult.error || 'Upload failed');
      }
      
      serverRecordingId = uploadResult.recording_id;
      
      // Update local record with server ID
      if (currentRecordingId) {
        await updateRecordingInDB(currentRecordingId, { 
          serverRecordingId: serverRecordingId,
          status: 'uploaded'
        });
      }
      
      // Request transcription
      const transcribeResult = await requestTranscription(serverRecordingId);
      
      if (!transcribeResult.success) {
        throw new Error(transcribeResult.error || 'Transcription failed');
      }
      
      // Success!
      if (currentRecordingId) {
        await updateRecordingInDB(currentRecordingId, { status: 'transcribed' });
      }
      
      setState(UIState.SUCCESS);
      
      if (onTranscriptReady) {
        onTranscriptReady(transcribeResult.transcript);
      }
      
    } catch (error) {
      console.error('Upload/transcribe error:', error);
      setError(error.message || 'Transcription failed');
    }
  }
  
  async function uploadToServer() {
    if (!currentBlob) {
      return { success: false, error: 'No recording available' };
    }
    
    try {
      const formData = new FormData();
      
      // Determine file extension from MIME type
      let ext = '.webm';
      if (currentBlob.type.includes('mp4') || currentBlob.type.includes('m4a')) {
        ext = '.m4a';
      } else if (currentBlob.type.includes('ogg')) {
        ext = '.ogg';
      }
      
      formData.append('audio', currentBlob, `recording${ext}`);
      
      // Include local recording ID for idempotency
      if (currentRecordingId) {
        formData.append('recording_id', currentRecordingId);
      }
      
      const response = await fetch('/api/stt/upload', {
        method: 'POST',
        body: formData
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        return { success: false, error: data.error || `Server error ${response.status}` };
      }
      
      return { success: true, recording_id: data.recording_id };
      
    } catch (error) {
      console.error('Upload error:', error);
      return { success: false, error: 'Network error during upload' };
    }
  }
  
  async function requestTranscription(recordingId) {
    try {
      const response = await fetch('/api/stt/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recording_id: recordingId })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        return { success: false, error: data.error || `Transcription error ${response.status}` };
      }
      
      return { success: true, transcript: data.transcript };
      
    } catch (error) {
      console.error('Transcription request error:', error);
      return { success: false, error: 'Network error during transcription' };
    }
  }
  
  async function retryTranscription() {
    // If we have a server recording ID, retry transcription on server
    if (serverRecordingId) {
      setState(UIState.PROCESSING);
      
      try {
        const result = await requestTranscription(serverRecordingId);
        
        if (!result.success) {
          throw new Error(result.error || 'Transcription failed');
        }
        
        if (currentRecordingId) {
          await updateRecordingInDB(currentRecordingId, { status: 'transcribed' });
        }
        
        setState(UIState.SUCCESS);
        
        if (onTranscriptReady) {
          onTranscriptReady(result.transcript);
        }
        
      } catch (error) {
        setError(error.message || 'Retry failed');
      }
      
      return;
    }
    
    // If no server ID, we need to re-upload first
    if (currentBlob || currentRecordingId) {
      // Try to load from IndexedDB if blob is missing
      if (!currentBlob && currentRecordingId) {
        const record = await getRecordingFromDB(currentRecordingId);
        if (record && record.blob) {
          currentBlob = record.blob;
        }
      }
      
      if (currentBlob) {
        await uploadAndTranscribe();
      } else {
        setError('Recording data not available for retry');
      }
    } else {
      setError('No recording available to retry');
    }
  }
  
  async function discardRecording() {
    // Discard on server if we have a server ID
    if (serverRecordingId) {
      try {
        await fetch('/api/stt/discard', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recording_id: serverRecordingId })
        });
      } catch (e) {
        console.warn('Failed to discard recording on server:', e);
      }
    }
    
    // Delete from IndexedDB
    if (currentRecordingId) {
      try {
        await deleteRecordingFromDB(currentRecordingId);
      } catch (e) {
        console.warn('Failed to delete recording from IndexedDB:', e);
      }
    }
    
    // Clear state
    currentRecordingId = null;
    currentBlob = null;
    serverRecordingId = null;
    lastError = null;
    
    localStorage.removeItem(ACTIVE_RECORDING_KEY);
    
    setState(UIState.IDLE);
  }
  
  function downloadRecording() {
    if (!currentBlob) return;
    
    const url = URL.createObjectURL(currentBlob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `recording-${currentRecordingId || 'audio'}.webm`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
  
  // === State Management ===
  
  function setState(newState) {
    currentState = newState;
    lastError = null;
    
    if (onStateChange) {
      onStateChange(newState, null);
    }
  }
  
  function setError(errorMessage) {
    currentState = UIState.ERROR;
    lastError = errorMessage;
    
    if (onStateChange) {
      onStateChange(UIState.ERROR, errorMessage);
    }
  }
  
  function getState() {
    return {
      state: currentState,
      error: lastError,
      hasRecording: !!(currentBlob || currentRecordingId),
      serverRecordingId: serverRecordingId
    };
  }
  
  // === Recovery on Page Load ===
  
  async function checkForPendingRecording() {
    const savedId = localStorage.getItem(ACTIVE_RECORDING_KEY);
    if (!savedId) return null;
    
    try {
      await openDB();
      const record = await getRecordingFromDB(savedId);
      
      if (!record) {
        localStorage.removeItem(ACTIVE_RECORDING_KEY);
        return null;
      }
      
      currentRecordingId = record.id;
      currentBlob = record.blob;
      serverRecordingId = record.serverRecordingId;
      
      // If we have a server ID, check its status
      if (serverRecordingId) {
        try {
          const response = await fetch(`/api/stt/recording/${serverRecordingId}`);
          const data = await response.json();
          
          if (response.ok) {
            if (data.status === 'transcribed' && data.transcript) {
              // Already transcribed!
              return {
                status: 'transcribed',
                transcript: data.transcript,
                recordingId: currentRecordingId
              };
            } else if (data.status === 'failed') {
              return {
                status: 'failed',
                error: data.error || 'Previous transcription failed',
                recordingId: currentRecordingId
              };
            } else if (data.status === 'processing') {
              return {
                status: 'processing',
                recordingId: currentRecordingId
              };
            }
          }
        } catch (e) {
          console.warn('Could not check server recording status:', e);
        }
      }
      
      // We have a local recording that needs processing
      return {
        status: 'pending',
        recordingId: currentRecordingId,
        hasLocalBlob: !!currentBlob
      };
      
    } catch (e) {
      console.error('Error checking for pending recording:', e);
      return null;
    }
  }
  
  // === Initialization ===
  
  async function init(callbacks) {
    onStateChange = callbacks.onStateChange || null;
    onTranscriptReady = callbacks.onTranscriptReady || null;
    onLevelUpdate = callbacks.onLevelUpdate || null;
    onTimeUpdate = callbacks.onTimeUpdate || null;
    
    // Open IndexedDB
    try {
      await openDB();
    } catch (e) {
      console.error('Failed to open IndexedDB:', e);
    }
    
    // Check for pending recordings
    const pending = await checkForPendingRecording();
    
    return pending;
  }
  
  // === Public API ===
  
  return {
    init,
    startRecording,
    stopRecording,
    cancelRecording,
    retryTranscription,
    discardRecording,
    downloadRecording,
    getState,
    formatTime,
    saveDraftText,
    loadDraftText,
    clearDraftText,
    UIState
  };
  
})();

// Export for use in modules if needed
if (typeof module !== 'undefined' && module.exports) {
  module.exports = CYOARecorder;
}

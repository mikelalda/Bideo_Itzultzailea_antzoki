// =============================================================================
// Bideo Itzultzailea - Frontend Application
// =============================================================================

const API_BASE = '';
let selectedFile = null;
let pollInterval = null;

// ---------------------------------------------------------------------------
// DOM Elements
// ---------------------------------------------------------------------------
const uploadArea = document.getElementById('uploadArea');
const videoFileInput = document.getElementById('videoFile');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const removeFileBtn = document.getElementById('removeFile');
const previewContainer = document.getElementById('previewContainer');
const videoPreview = document.getElementById('videoPreview');
const sourceLang = document.getElementById('sourceLang');
const targetLang = document.getElementById('targetLang');
const swapLangs = document.getElementById('swapLangs');
const voiceSelect = document.getElementById('voice');
const cloneVoice = document.getElementById('cloneVoice');
const translateForm = document.getElementById('translateForm');
const submitBtn = document.getElementById('submitBtn');
const progressCard = document.getElementById('progressCard');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const resultsCard = document.getElementById('resultsCard');
const originalText = document.getElementById('originalText');
const translatedText = document.getElementById('translatedText');
const downloadBtn = document.getElementById('downloadBtn');
const newTranslationBtn = document.getElementById('newTranslation');
const errorCard = document.getElementById('errorCard');
const errorText = document.getElementById('errorText');
const retryBtn = document.getElementById('retryBtn');

// Step-by-step review cards
const transcriptReviewCard = document.getElementById('transcriptReviewCard');
const transcriptSubtitleEditor = document.getElementById('transcriptSubtitleEditor');
const transcriptCaptionEditor = document.getElementById('transcriptCaptionEditor');
const transcriptSentencesPanel = document.getElementById('transcriptSentencesPanel');
const transcriptCaptionsPanel = document.getElementById('transcriptCaptionsPanel');
const transcriptViewButtons = document.querySelectorAll('.transcript-view-btn');
const addTranscriptSubtitleBtn = document.getElementById('addTranscriptSubtitleBtn');
const approveTranscriptBtn = document.getElementById('approveTranscriptBtn');
const downloadTranscriptBtn = document.getElementById('downloadTranscriptBtn');
const uploadTranscriptBtn = document.getElementById('uploadTranscriptBtn');
const transcriptFileInput = document.getElementById('transcriptFileInput');
const translationReviewCard = document.getElementById('translationReviewCard');
const translationSubtitleEditor = document.getElementById('translationSubtitleEditor');
const approveTranslationBtn = document.getElementById('approveTranslationBtn');
const synthesisReviewCard = document.getElementById('synthesisReviewCard');
const approveSynthesisBtn = document.getElementById('approveSynthesisBtn');

let currentJobId = null;
let activeTranscriptView = 'sentences';
let transcriptSyncVersion = 0;
let transcriptSyncQueue = Promise.resolve();

const VOICES = [
    { value: 'natural', label: 'Naturala' },
    { value: 'warm', label: 'Beroa' },
    { value: 'dramatic', label: 'Dramatikoa' },
    { value: 'serious', label: 'Serioa' },
    { value: 'joyful', label: 'Alaia' },
];

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    updateVoiceOptions();
    setInterval(checkHealth, 30000);
});

// ---------------------------------------------------------------------------
// Health Check
// ---------------------------------------------------------------------------
async function checkHealth() {
    const dots = {
        orchestrator: document.getElementById('statusOrchestrator'),
        whisper: document.getElementById('statusWhisper'),
        antzoki: document.getElementById('statusAntzoki'),
    };

    // Set loading
    Object.values(dots).forEach(d => d.className = 'status-dot loading');

    try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json();

        dots.orchestrator.className = 'status-dot ok';

        dots.whisper.className = data.whisper && typeof data.whisper === 'object'
            ? 'status-dot ok' : 'status-dot error';

        dots.antzoki.className = data.antzoki && data.antzoki.status === 'ok'
            ? 'status-dot ok' : 'status-dot error';
    } catch {
        dots.orchestrator.className = 'status-dot error';
        dots.whisper.className = 'status-dot error';
        dots.antzoki.className = 'status-dot error';
    }
}

// ---------------------------------------------------------------------------
// File Upload
// ---------------------------------------------------------------------------
uploadArea.addEventListener('click', () => videoFileInput.click());

uploadArea.addEventListener('dragover', e => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', e => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
    }
});

videoFileInput.addEventListener('change', () => {
    if (videoFileInput.files.length > 0) {
        handleFile(videoFileInput.files[0]);
    }
});

removeFileBtn.addEventListener('click', () => {
    clearFile();
});

function handleFile(file) {
    const validTypes = ['video/mp4', 'video/avi', 'video/x-msvideo', 'video/x-matroska',
                        'video/quicktime', 'video/webm', 'video/mpeg'];

    // Also accept by extension
    const ext = file.name.split('.').pop().toLowerCase();
    const validExts = ['mp4', 'avi', 'mkv', 'mov', 'webm', 'mpeg', 'mpg'];

    if (!validTypes.includes(file.type) && !validExts.includes(ext)) {
        showError('Fitxategi mota ez da onartzen. Erabili MP4, AVI, MKV, MOV edo WEBM.');
        return;
    }

    selectedFile = file;
    fileName.textContent = `${file.name} (${formatSize(file.size)})`;
    fileInfo.style.display = 'flex';
    uploadArea.style.display = 'none';

    // Video preview
    const url = URL.createObjectURL(file);
    videoPreview.src = url;
    previewContainer.style.display = 'block';
}

function clearFile() {
    selectedFile = null;
    videoFileInput.value = '';
    fileInfo.style.display = 'none';
    uploadArea.style.display = 'block';
    previewContainer.style.display = 'none';
    videoPreview.src = '';
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ---------------------------------------------------------------------------
// Language & Voice
// ---------------------------------------------------------------------------
swapLangs.addEventListener('click', () => {
    const src = sourceLang.value;
    const tgt = targetLang.value;
    sourceLang.value = tgt;
    targetLang.value = src;
    updateVoiceOptions();
});

sourceLang.addEventListener('change', () => {
    if (sourceLang.value === targetLang.value) {
        targetLang.value = sourceLang.value === 'es' ? 'eu' : 'es';
    }
    updateVoiceOptions();
});

targetLang.addEventListener('change', () => {
    if (targetLang.value === sourceLang.value) {
        sourceLang.value = targetLang.value === 'es' ? 'eu' : 'es';
    }
    updateVoiceOptions();
});

function updateVoiceOptions() {
    voiceSelect.innerHTML = '';
    VOICES.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.value;
        opt.textContent = v.label;
        voiceSelect.appendChild(opt);
    });
}

// ---------------------------------------------------------------------------
// Form Submission (urrats-1: bideoa igo + transkribatu)
// ---------------------------------------------------------------------------
translateForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!selectedFile) {
        showError('Mesedez, hautatu bideo bat.');
        return;
    }

    if (sourceLang.value === targetLang.value) {
        showError('Jatorrizko eta helburu hizkuntzak desberdinak izan behar dira.');
        return;
    }

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('source_lang', sourceLang.value);
    formData.append('target_lang', targetLang.value);
    formData.append('voice', voiceSelect.value);
    formData.append('clone_voice', String(cloneVoice.checked));

    hideError();
    resultsCard.style.display = 'none';
    transcriptReviewCard.style.display = 'none';
    translationReviewCard.style.display = 'none';
    synthesisReviewCard.style.display = 'none';
    progressCard.style.display = 'block';
    submitBtn.disabled = true;
    resetProgress();

    try {
        // Berehala itzultzen du job_id bat -- pipeline osoa ez du itxaron
        // behar (HF Spaces-en proxy-ak eskaera luzeak mozten ditu ~60s-tara).
        const res = await fetch(`${API_BASE}/api/translate`, {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Translation failed');
        }

        const { job_id } = await res.json();
        currentJobId = job_id;
        startPolling(job_id);

    } catch (err) {
        showError(err.message);
        progressCard.style.display = 'none';
        submitBtn.disabled = false;
    }
});

// ---------------------------------------------------------------------------
// Polling: pipeline pausuz pausu doa, eta erabiltzailearen onarpenaren zain
// gelditzen da urrats bakoitzaren ondoren (transkripzioa, itzulpena,
// sintesia). Job-aren egoerak dio zein card erakutsi.
// ---------------------------------------------------------------------------
function startPolling(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/job/${jobId}`);
            const data = await res.json();

            updateProgress(data.state, data.progress, data.detail);

            switch (data.state) {
                case 'awaiting_transcript_review':
                    stopPolling();
                    renderTranscriptViews(data);
                    progressCard.style.display = 'none';
                    transcriptReviewCard.style.display = 'block';
                    submitBtn.disabled = false;
                    break;

                case 'awaiting_translation_review':
                    stopPolling();
                    renderSubtitleEditor(translationSubtitleEditor, data.subtitles || []);
                    progressCard.style.display = 'none';
                    translationReviewCard.style.display = 'block';
                    break;

                case 'awaiting_synthesis_review':
                    stopPolling();
                    progressCard.style.display = 'none';
                    synthesisReviewCard.style.display = 'block';
                    break;

                case 'completed': {
                    stopPolling();
                    markAllStepsDone();
                    const result = data.result || {};
                    originalText.textContent = result.transcription || '(ez dago testurik)';
                    translatedText.textContent = result.translated_text || '(ez dago testurik)';
                    downloadBtn.href = result.download_url;
                    setTimeout(() => {
                        progressCard.style.display = 'none';
                        resultsCard.style.display = 'block';
                    }, 800);
                    break;
                }

                case 'error':
                    stopPolling();
                    submitBtn.disabled = false;
                    showError(data.detail || 'Translation failed');
                    progressCard.style.display = 'none';
                    break;
            }
        } catch (err) {
            stopPolling();
            submitBtn.disabled = false;
            showError(err.message);
        }
    }, 1500);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

function createSubtitleRow(subtitle, index) {
    const row = document.createElement('div');
    row.className = 'subtitle-row';

    const number = document.createElement('span');
    number.className = 'subtitle-number';
    number.textContent = index + 1;

    const start = document.createElement('input');
    start.type = 'number';
    start.className = 'subtitle-time subtitle-start';
    start.min = '0';
    start.step = '0.001';
    start.value = Number(subtitle.start || 0).toFixed(3);
    start.setAttribute('aria-label', `${index + 1}. azpitituluaren hasiera`);

    const end = document.createElement('input');
    end.type = 'number';
    end.className = 'subtitle-time subtitle-end';
    end.min = '0.001';
    end.step = '0.001';
    end.value = Number(subtitle.end || 2).toFixed(3);
    end.setAttribute('aria-label', `${index + 1}. azpitituluaren amaiera`);

    const text = document.createElement('textarea');
    text.className = 'subtitle-text';
    text.rows = 2;
    text.value = subtitle.text || '';
    text.setAttribute('aria-label', `${index + 1}. azpitituluaren testua`);

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'subtitle-delete';
    remove.textContent = '×';
    remove.title = 'Azpititulua ezabatu';
    remove.setAttribute('aria-label', `${index + 1}. azpititulua ezabatu`);
    remove.addEventListener('click', () => {
        const editor = row.parentElement;
        row.remove();
        renumberSubtitleRows(editor);
        if (editor.classList.contains('transcript-editor')) {
            syncTranscriptEditor(editor).catch(err => showError(err.message));
        }
    });

    row.append(number, start, end, text, remove);
    row.addEventListener('click', event => {
        if (event.target.matches('input, textarea, button')) return;
        videoPreview.currentTime = Number(start.value) || 0;
    });
    return row;
}

function renderSubtitleEditor(editor, subtitles) {
    editor.replaceChildren();
    subtitles.forEach((subtitle, index) => {
        editor.appendChild(createSubtitleRow(subtitle, index));
    });
}

function renderTranscriptViews(data) {
    renderSubtitleEditor(transcriptSubtitleEditor, data.sentences || data.subtitles || []);
    renderSubtitleEditor(transcriptCaptionEditor, data.captions || []);
}

function getActiveTranscriptEditor() {
    return activeTranscriptView === 'captions'
        ? transcriptCaptionEditor
        : transcriptSubtitleEditor;
}

function setTranscriptView(view) {
    activeTranscriptView = view;
    transcriptSentencesPanel.hidden = view !== 'sentences';
    transcriptCaptionsPanel.hidden = view !== 'captions';
    transcriptViewButtons.forEach(button => {
        const isActive = button.dataset.view === view;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', String(isActive));
    });
}

function syncTranscriptEditor(editor) {
    if (!currentJobId) return null;
    const view = editor === transcriptCaptionEditor ? 'captions' : 'sentences';
    const version = ++transcriptSyncVersion;
    const subtitles = collectSubtitles(editor);
    const operation = transcriptSyncQueue.catch(() => {}).then(async () => {
        const res = await fetch(`${API_BASE}/api/job/${currentJobId}/transcript`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ view, subtitles }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Transkripzioa ezin izan da sinkronizatu');
        }
        const data = await res.json();
        if (version === transcriptSyncVersion) renderTranscriptViews(data);
        hideError();
        return data;
    });
    transcriptSyncQueue = operation;
    return operation;
}

transcriptViewButtons.forEach(button => {
    button.addEventListener('click', () => setTranscriptView(button.dataset.view));
});

[transcriptSubtitleEditor, transcriptCaptionEditor].forEach(editor => {
    editor.addEventListener('change', () => {
        syncTranscriptEditor(editor).catch(err => showError(err.message));
    });
});

addTranscriptSubtitleBtn.addEventListener('click', () => addSubtitle(getActiveTranscriptEditor()));

function renumberSubtitleRows(editor) {
    [...editor.querySelectorAll('.subtitle-row')].forEach((row, index) => {
        row.querySelector('.subtitle-number').textContent = index + 1;
    });
}

function addSubtitle(editor) {
    const rows = editor.querySelectorAll('.subtitle-row');
    const lastEnd = rows.length
        ? Number(rows[rows.length - 1].querySelector('.subtitle-end').value)
        : 0;
    editor.appendChild(createSubtitleRow({ start: lastEnd, end: lastEnd + 2, text: '' }, rows.length));
    editor.lastElementChild.querySelector('.subtitle-text').focus();
}

function collectSubtitles(editor) {
    const subtitles = [...editor.querySelectorAll('.subtitle-row')].map((row, index) => {
        const start = Number(row.querySelector('.subtitle-start').value);
        const end = Number(row.querySelector('.subtitle-end').value);
        const text = row.querySelector('.subtitle-text').value.trim();
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || !text) {
            throw new Error(`${index + 1}. azpititulua osatu eta denborak zuzendu.`);
        }
        return { start, end, text };
    });
    if (!subtitles.length) throw new Error('Gutxienez azpititulu bat behar da.');
    return subtitles;
}

function formatSrtTimestamp(seconds) {
    const totalMillis = Math.max(0, Math.round(seconds * 1000));
    const hours = Math.floor(totalMillis / 3600000);
    const minutes = Math.floor((totalMillis % 3600000) / 60000);
    const secs = Math.floor((totalMillis % 60000) / 1000);
    const millis = totalMillis % 1000;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(millis).padStart(3, '0')}`;
}

function subtitlesToSrt(subtitles) {
    return subtitles.map((subtitle, index) => [
        index + 1,
        `${formatSrtTimestamp(subtitle.start)} --> ${formatSrtTimestamp(subtitle.end)}`,
        subtitle.text,
        '',
    ].join('\n')).join('\n');
}

function parseSrtTimestamp(value) {
    const match = value.trim().match(/^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})$/);
    if (!match) throw new Error(`SRT denbora baliogabea: ${value}`);
    return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4]) / 1000;
}

function srtToSubtitles(srt) {
    const normalized = srt.replace(/\r\n?/g, '\n').trim();
    if (!normalized) throw new Error('SRT fitxategia hutsik dago.');

    const subtitles = normalized.split(/\n\s*\n/).map((block, index) => {
        const lines = block.split('\n');
        const timeIndex = lines.findIndex(line => line.includes('-->'));
        if (timeIndex < 0) throw new Error(`${index + 1}. SRT blokeak ez du denborarik.`);
        const times = lines[timeIndex].split(/\s*-->\s*/);
        if (times.length !== 2) throw new Error(`${index + 1}. SRT blokearen denbora baliogabea da.`);
        const text = lines.slice(timeIndex + 1).join(' ').trim();
        if (!text) throw new Error(`${index + 1}. SRT blokeak ez du testurik.`);
        return { start: parseSrtTimestamp(times[0]), end: parseSrtTimestamp(times[1]), text };
    });

    subtitles.forEach((subtitle, index) => {
        if (subtitle.end <= subtitle.start) {
            throw new Error(`${index + 1}. SRT blokearen amaiera hasieraren ondoren izan behar da.`);
        }
    });
    return subtitles;
}

function downloadTranscript() {
    try {
        const srt = subtitlesToSrt(collectSubtitles(transcriptCaptionEditor));
        const blobUrl = URL.createObjectURL(new Blob([srt], { type: 'application/x-subrip;charset=utf-8' }));
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = `${selectedFile?.name.replace(/\.[^.]+$/, '') || 'transkripzioa'}.srt`;
        link.click();
        URL.revokeObjectURL(blobUrl);
    } catch (err) {
        showError(err.message);
    }
}

async function uploadTranscript(file) {
    try {
        renderSubtitleEditor(transcriptCaptionEditor, srtToSubtitles(await file.text()));
        await syncTranscriptEditor(transcriptCaptionEditor);
        setTranscriptView('captions');
    } catch (err) {
        showError(err.message);
    } finally {
        transcriptFileInput.value = '';
    }
}

function syncActiveSubtitle() {
    const rows = [...transcriptCaptionEditor.querySelectorAll('.subtitle-row')];
    const currentTime = videoPreview.currentTime;
    let activeRow = null;
    rows.forEach(row => {
        const start = Number(row.querySelector('.subtitle-start').value);
        const end = Number(row.querySelector('.subtitle-end').value);
        const isActive = currentTime >= start && currentTime < end;
        row.classList.toggle('active', isActive);
        if (isActive) activeRow = row;
    });
    if (activeRow && !activeRow.matches(':focus-within')) {
        const rowTop = activeRow.offsetTop;
        const rowBottom = rowTop + activeRow.offsetHeight;
        const editorTop = transcriptCaptionEditor.scrollTop;
        const editorBottom = editorTop + transcriptCaptionEditor.clientHeight;
        if (rowTop < editorTop || rowBottom > editorBottom) {
            transcriptCaptionEditor.scrollTo({
                top: rowTop - transcriptCaptionEditor.clientHeight / 2 + activeRow.offsetHeight / 2,
                behavior: 'smooth',
            });
        }
    }
}

downloadTranscriptBtn.addEventListener('click', downloadTranscript);
uploadTranscriptBtn.addEventListener('click', () => transcriptFileInput.click());
transcriptFileInput.addEventListener('change', () => {
    if (transcriptFileInput.files.length) uploadTranscript(transcriptFileInput.files[0]);
});
videoPreview.addEventListener('timeupdate', syncActiveSubtitle);
videoPreview.addEventListener('seeked', syncActiveSubtitle);

async function saveSubtitles(editor) {
    const res = await fetch(`${API_BASE}/api/job/${currentJobId}/subtitles`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subtitles: collectSubtitles(editor) }),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Azpitituluak ezin izan dira gorde');
    }
}

document.querySelectorAll('.add-subtitle-btn').forEach(button => {
    button.addEventListener('click', () => addSubtitle(document.getElementById(button.dataset.editor)));
});

// ---------------------------------------------------------------------------
// Urrats-1 onarpena: azpitituluak bidali eta itzulpena abiarazi
// ---------------------------------------------------------------------------
approveTranscriptBtn.addEventListener('click', async () => {
    if (!currentJobId) return;
    approveTranscriptBtn.disabled = true;
    try {
        await syncTranscriptEditor(getActiveTranscriptEditor());

        const approveRes = await fetch(`${API_BASE}/api/job/${currentJobId}/approve`, {
            method: 'POST',
        });
        if (!approveRes.ok) {
            const err = await approveRes.json().catch(() => ({ detail: approveRes.statusText }));
            throw new Error(err.detail || 'Ezin izan da itzulpena abiarazi');
        }

        transcriptReviewCard.style.display = 'none';
        progressCard.style.display = 'block';
        startPolling(currentJobId);
    } catch (err) {
        showError(err.message);
    } finally {
        approveTranscriptBtn.disabled = false;
    }
});

// ---------------------------------------------------------------------------
// Urrats-2 onarpena: itzulpena onartu, ahotsa sortu
// ---------------------------------------------------------------------------
approveTranslationBtn.addEventListener('click', async () => {
    if (!currentJobId) return;
    approveTranslationBtn.disabled = true;
    try {
        await saveSubtitles(translationSubtitleEditor);

        const approveRes = await fetch(`${API_BASE}/api/job/${currentJobId}/approve`, {
            method: 'POST',
        });
        if (!approveRes.ok) {
            const err = await approveRes.json().catch(() => ({ detail: approveRes.statusText }));
            throw new Error(err.detail || 'Ezin izan da ahotsa abiarazi');
        }

        translationReviewCard.style.display = 'none';
        progressCard.style.display = 'block';
        startPolling(currentJobId);
    } catch (err) {
        showError(err.message);
    } finally {
        approveTranslationBtn.disabled = false;
    }
});

// ---------------------------------------------------------------------------
// Urrats-3 onarpena: ahotsa onartu, bideo finala sortu
// ---------------------------------------------------------------------------
approveSynthesisBtn.addEventListener('click', async () => {
    if (!currentJobId) return;
    approveSynthesisBtn.disabled = true;
    try {
        const approveRes = await fetch(`${API_BASE}/api/job/${currentJobId}/approve`, {
            method: 'POST',
        });
        if (!approveRes.ok) {
            const err = await approveRes.json().catch(() => ({ detail: approveRes.statusText }));
            throw new Error(err.detail || 'Ezin izan da bideo finala abiarazi');
        }

        synthesisReviewCard.style.display = 'none';
        progressCard.style.display = 'block';
        startPolling(currentJobId);
    } catch (err) {
        showError(err.message);
    } finally {
        approveSynthesisBtn.disabled = false;
    }
});

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------
const STEP_ORDER = [
    'uploading', 'extracting_audio', 'transcribing',
    'translating', 'synthesizing', 'combining', 'finalizing', 'completed'
];

function resetProgress() {
    progressBar.style.width = '5%';
    progressText.textContent = 'Hasieratzen...';
    document.querySelectorAll('.step').forEach(s => {
        s.classList.remove('active', 'done');
    });
}

function updateProgress(step, progress, detail) {
    progressBar.style.width = `${Math.max(progress, 5)}%`;
    progressText.textContent = detail || step;

    const stepIdx = STEP_ORDER.indexOf(step);
    document.querySelectorAll('.step').forEach(el => {
        const elStep = el.dataset.step;
        const elIdx = STEP_ORDER.indexOf(elStep);
        el.classList.remove('active', 'done');
        if (elIdx < stepIdx) el.classList.add('done');
        else if (elIdx === stepIdx) el.classList.add('active');
    });
}

function markAllStepsDone() {
    document.querySelectorAll('.step').forEach(s => {
        s.classList.remove('active');
        s.classList.add('done');
    });
}

// ---------------------------------------------------------------------------
// Error Handling
// ---------------------------------------------------------------------------
function showError(message) {
    errorText.textContent = message;
    errorCard.style.display = 'block';
}

function hideError() {
    errorCard.style.display = 'none';
}

retryBtn.addEventListener('click', () => {
    hideError();
});

newTranslationBtn.addEventListener('click', () => {
    resultsCard.style.display = 'none';
    transcriptReviewCard.style.display = 'none';
    translationReviewCard.style.display = 'none';
    synthesisReviewCard.style.display = 'none';
    currentJobId = null;
    clearFile();
    resetProgress();
});

// ---------------------------------------------------------------------------
// Progress reporting is now REAL, not simulated: see startPolling() above, which
// polls GET /api/job/{job_id} while the backend runs the pipeline as a
// background task. This replaces the old simulateProgress() timer-based
// fake progress bar, which was needed only because /api/translate used to
// block until the whole pipeline finished (and got killed by the HF Spaces
// proxy's ~60s timeout on long-running requests).

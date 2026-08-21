// =============================================================================
// aHoTTS Browser - Unified TTS for browser environments
//
// Three engines available in parallel:
//   1. Transformers.js  – client-side VITS inference via @huggingface/transformers
//   2. Web Speech API   – native browser voices (Chrome, Firefox, Safari …)
//   3. aHoTTS REST API  – server-side synthesis through the FastAPI backend
// =============================================================================

const TRANSFORMERS_CDN =
  "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3";

// Default Transformers.js model map (MMS-TTS models known to work with the
// pipeline).  Users may override or extend via AhoTTSManager.configure().
const DEFAULT_TRANSFORMERS_MODELS = {
  eu: { id: "Xenova/mms-tts-eus", label: "MMS-TTS Euskara" },
  es: { id: "Xenova/mms-tts-spa", label: "MMS-TTS Español" },
  gl: { id: "Xenova/mms-tts-glg", label: "MMS-TTS Galego" },
  ca: { id: "Xenova/mms-tts-cat", label: "MMS-TTS Català" },
};

// BCP-47 codes used by the Web Speech API for each aHoTTS language
const WEBSPEECH_LANG_MAP = {
  eu: "eu",
  es: "es",
  gl: "gl",
  ca: "ca",
};

// ─── Transformers.js engine ──────────────────────────────────────────────────

class TransformersEngine {
  constructor() {
    this._pipeline = null;
    this._pipelineFn = null;
    this._currentModelId = null;
    this._loading = false;
    this._models = { ...DEFAULT_TRANSFORMERS_MODELS };
  }

  get name() {
    return "transformers";
  }

  setModels(models) {
    Object.assign(this._models, models);
  }

  async _ensureLib() {
    if (this._pipelineFn) return;
    const mod = await import(/* webpackIgnore: true */ TRANSFORMERS_CDN);
    this._pipelineFn = mod.pipeline;
  }

  async _loadPipeline(modelId, onProgress) {
    if (this._currentModelId === modelId && this._pipeline) return;
    this._loading = true;
    try {
      await this._ensureLib();
      this._pipeline = await this._pipelineFn(
        "text-to-speech",
        modelId,
        {
          dtype: "fp32",
          progress_callback: onProgress || undefined,
        }
      );
      this._currentModelId = modelId;
    } finally {
      this._loading = false;
    }
  }

  getVoices() {
    return Object.entries(this._models).map(([lang, m]) => ({
      engine: this.name,
      language: lang,
      voiceId: m.id,
      label: m.label,
    }));
  }

  async synthesize(text, language, { onProgress } = {}) {
    const model = this._models[language];
    if (!model) {
      throw new Error(
        `Transformers.js: no model configured for language "${language}"`
      );
    }
    await this._loadPipeline(model.id, onProgress);
    const result = await this._pipeline(text);
    return this._toAudioBuffer(result);
  }

  _toAudioBuffer(result) {
    const sampleRate = result.sampling_rate;
    const audioData = result.audio;

    // audioData can be a Float32Array or nested array
    const samples =
      audioData instanceof Float32Array
        ? audioData
        : new Float32Array(audioData.flat());

    // Build a proper WAV blob so it can be played via <audio>
    return createWavBlob(samples, sampleRate);
  }

  isLoading() {
    return this._loading;
  }
}

// ─── Web Speech API engine ──────────────────────────────────────────────────

class WebSpeechEngine {
  constructor() {
    this._synth =
      typeof window !== "undefined" ? window.speechSynthesis : null;
  }

  get name() {
    return "webspeech";
  }

  isSupported() {
    return !!this._synth;
  }

  getVoices() {
    if (!this._synth) return [];
    const voices = this._synth.getVoices();
    return voices.map((v) => ({
      engine: this.name,
      language: v.lang,
      voiceId: v.voiceURI,
      label: `${v.name} (${v.lang})`,
      native: true,
      nativeVoice: v,
    }));
  }

  getVoicesForLanguage(langCode) {
    const prefix = WEBSPEECH_LANG_MAP[langCode] || langCode;
    return this.getVoices().filter((v) =>
      v.language.toLowerCase().startsWith(prefix.toLowerCase())
    );
  }

  synthesize(text, voiceIdOrLang, { rate = 1, pitch = 1 } = {}) {
    return new Promise((resolve, reject) => {
      if (!this._synth) {
        return reject(new Error("Web Speech API not supported"));
      }

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = rate;
      utterance.pitch = pitch;

      // Try to match a voice
      const voices = this._synth.getVoices();
      const match =
        voices.find((v) => v.voiceURI === voiceIdOrLang) ||
        voices.find((v) =>
          v.lang.toLowerCase().startsWith(voiceIdOrLang.toLowerCase())
        );
      if (match) {
        utterance.voice = match;
        utterance.lang = match.lang;
      } else {
        utterance.lang = voiceIdOrLang;
      }

      utterance.onend = () => resolve(null); // audio plays inline
      utterance.onerror = (e) => reject(e);
      this._synth.speak(utterance);
    });
  }

  stop() {
    if (this._synth) this._synth.cancel();
  }
}

// ─── REST API engine ────────────────────────────────────────────────────────

class APIEngine {
  constructor(baseUrl) {
    this.baseUrl = (baseUrl || "").replace(/\/+$/, "");
  }

  get name() {
    return "api";
  }

  setBaseUrl(url) {
    this.baseUrl = (url || "").replace(/\/+$/, "");
  }

  async getVoices() {
    const res = await fetch(`${this.baseUrl}/voices`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    const data = await res.json();
    const voices = [];
    for (const lang of data.languages) {
      for (const v of lang.voices) {
        voices.push({
          engine: this.name,
          language: v.language,
          voiceId: v.name,
          label: `${v.name} – ${lang.name}`,
          downloaded: v.downloaded,
        });
      }
    }
    return voices;
  }

  async synthesize(text, language, voice) {
    const res = await fetch(`${this.baseUrl}/synthesize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language, voice }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API error: ${res.status}`);
    }
    return await res.blob();
  }

  async downloadVoice(language, voice) {
    const res = await fetch(`${this.baseUrl}/download/${language}/${voice}`, {
      method: "POST",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Download error: ${res.status}`);
    }
    return await res.json();
  }
}

// ─── Unified manager ────────────────────────────────────────────────────────

class AhoTTSManager {
  /**
   * @param {object}  opts
   * @param {string}  opts.apiUrl          – base URL for the REST API
   * @param {object}  opts.transformersModels – override/extend model map
   */
  constructor(opts = {}) {
    this.api = new APIEngine(opts.apiUrl || window.location.origin);
    this.transformers = new TransformersEngine();
    this.webSpeech = new WebSpeechEngine();

    if (opts.transformersModels) {
      this.transformers.setModels(opts.transformersModels);
    }
  }

  /**
   * Return all voices from every engine, merged into a single list.
   * Each entry has an `engine` field ("api", "transformers", "webspeech").
   */
  async getAllVoices() {
    const results = { api: [], transformers: [], webspeech: [] };

    // API voices (may fail if server is unreachable)
    try {
      results.api = await this.api.getVoices();
    } catch {
      /* server not available */
    }

    results.transformers = this.transformers.getVoices();
    results.webspeech = this.webSpeech.getVoices();

    return results;
  }

  /**
   * Synthesize text using the selected engine.
   *
   * @param {string} text
   * @param {object} opts
   * @param {"api"|"transformers"|"webspeech"} opts.engine
   * @param {string} opts.language   – language code (eu, es, gl, ca)
   * @param {string} opts.voice      – voice id (for api) or voiceURI (webspeech)
   * @param {Function} opts.onProgress – progress callback (transformers only)
   * @returns {Promise<Blob|null>}     audio Blob (WAV) or null for webspeech
   */
  async synthesize(text, opts = {}) {
    const engine = opts.engine || "api";

    switch (engine) {
      case "api":
        return this.api.synthesize(text, opts.language, opts.voice);

      case "transformers":
        return this.transformers.synthesize(text, opts.language, {
          onProgress: opts.onProgress,
        });

      case "webspeech":
        return this.webSpeech.synthesize(text, opts.voice || opts.language, {
          rate: opts.rate,
          pitch: opts.pitch,
        });

      default:
        throw new Error(`Unknown engine: "${engine}"`);
    }
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Build a WAV Blob from raw PCM Float32 samples.
 */
function createWavBlob(samples, sampleRate) {
  const numChannels = 1;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");

  // fmt  sub-chunk
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);

  // data sub-chunk
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  // PCM samples (clamp to [-1, 1] then scale to int16)
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}

function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

// ─── Exports ─────────────────────────────────────────────────────────────────

export {
  AhoTTSManager,
  TransformersEngine,
  WebSpeechEngine,
  APIEngine,
  createWavBlob,
};

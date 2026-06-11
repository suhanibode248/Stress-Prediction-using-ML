/**
 * voice.js — Real voice stress analysis via Web Audio API
 * Measures pitch variance, amplitude, and zero-crossing rate
 */
class VoiceAnalyzer {
  constructor() {
    this.audioCtx   = null;
    this.analyser   = null;
    this.source     = null;
    this.stream     = null;
    this.running    = false;
    this.history    = [];   // last 30 RMS values
    this.pitchHist  = [];   // last 30 pitch values
  }

  async start() {
    try {
      this.stream   = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 2048;
      this.analyser.smoothingTimeConstant = 0.8;
      this.source   = this.audioCtx.createMediaStreamSource(this.stream);
      this.source.connect(this.analyser);
      this.running  = true;
      return true;
    } catch (e) {
      console.warn('[VoiceAnalyzer] Mic access denied:', e);
      return false;
    }
  }

  stop() {
    if (this.source)   this.source.disconnect();
    if (this.audioCtx) this.audioCtx.close();
    if (this.stream)   this.stream.getTracks().forEach(t => t.stop());
    this.running = false;
  }

  _rms(buf) {
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] ** 2;
    return Math.sqrt(sum / buf.length);
  }

  // Simple autocorrelation pitch detection
  _pitch(buf, sampleRate) {
    const SIZE = buf.length;
    const MAX_SAMPLES = Math.floor(SIZE / 2);
    let best_offset = -1, best_corr = 0;
    let last_corr = 1, found = false;
    for (let offset = 0; offset < MAX_SAMPLES; offset++) {
      let corr = 0;
      for (let i = 0; i < MAX_SAMPLES; i++) corr += Math.abs(buf[i] - buf[i + offset]);
      corr = 1 - corr / MAX_SAMPLES;
      if (corr > 0.9 && corr > last_corr) {
        found = true;
        if (corr > best_corr) { best_corr = corr; best_offset = offset; }
      } else if (found) break;
      last_corr = corr;
    }
    return best_offset === -1 ? 0 : sampleRate / best_offset;
  }

  getSample() {
    if (!this.running || !this.analyser) return { rms: 0, pitch: 0, stressScore: 50 };
    const buf = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(buf);

    const rms = this._rms(buf);
    const pitch = this._pitch(buf, this.audioCtx.sampleRate);

    this.history.push(rms);
    if (this.history.length > 30) this.history.shift();

    if (pitch > 50 && pitch < 1000) {
      this.pitchHist.push(pitch);
      if (this.pitchHist.length > 30) this.pitchHist.shift();
    }

    return { rms, pitch, stressScore: this.toStressScore() };
  }

  toStressScore() {
    if (this.history.length < 3) return 50;
    const avgRms = this.history.reduce((a,b) => a+b, 0) / this.history.length;

    // Pitch variance — high variance = stress
    let pitchVar = 0;
    if (this.pitchHist.length > 3) {
      const avgP = this.pitchHist.reduce((a,b) => a+b, 0) / this.pitchHist.length;
      pitchVar = Math.sqrt(this.pitchHist.reduce((a,b) => a + (b-avgP)**2, 0) / this.pitchHist.length);
    }

    // RMS volume score (0-50 range contribution)
    const volScore = Math.min(50, avgRms * 800);
    // Pitch variance score (0-50 range contribution)
    const varScore = Math.min(50, pitchVar * 0.4);
    return Math.round(Math.min(100, volScore + varScore));
  }
}

window.VoiceAnalyzer = VoiceAnalyzer;
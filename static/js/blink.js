/**
 * blink.js — Real blink detection using MediaPipe Face Mesh
 * Tracks EAR (Eye Aspect Ratio) to count blinks per minute
 */
class BlinkDetector {
  constructor() {
    this.blinksInWindow = [];
    this.windowMs = 60000;
    this.earThreshold = 0.22;
    this.blinkCooldown = 180; // ms between blinks
    this.lastBlinkTime = 0;
    this.eyeClosed = false;

    // MediaPipe landmark indices for left/right eye
    this.LEFT_EYE  = [362,385,387,263,373,380];
    this.RIGHT_EYE = [33, 160,158,133,153,144];
  }

  _dist(a, b) {
    return Math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2);
  }

  _ear(pts, idx) {
    const [p1,p2,p3,p4,p5,p6] = idx.map(i => pts[i]);
    const v1 = this._dist(p2, p6);
    const v2 = this._dist(p3, p5);
    const h  = this._dist(p1, p4);
    return (v1 + v2) / (2.0 * h);
  }

  update(landmarks) {
    if (!landmarks || landmarks.length === 0) return this.getBPM();
    const pts = landmarks;
    const leftEAR  = this._ear(pts, this.LEFT_EYE);
    const rightEAR = this._ear(pts, this.RIGHT_EYE);
    const ear = (leftEAR + rightEAR) / 2;

    const now = Date.now();
    if (ear < this.earThreshold && !this.eyeClosed) {
      this.eyeClosed = true;
    } else if (ear >= this.earThreshold && this.eyeClosed) {
      this.eyeClosed = false;
      if (now - this.lastBlinkTime > this.blinkCooldown) {
        this.blinksInWindow.push(now);
        this.lastBlinkTime = now;
      }
    }
    // purge old entries
    this.blinksInWindow = this.blinksInWindow.filter(t => now - t < this.windowMs);
    return this.getBPM();
  }

  getBPM() {
    const now = Date.now();
    const recent = this.blinksInWindow.filter(t => now - t < this.windowMs);
    return recent.length; // blinks in last minute
  }

  // Convert BPM to 0-100 stress score
  // Normal = 15-20 bpm; very low (<8) or very high (>30) = stress
  toStressScore(bpm) {
    if (bpm === 0) return 50; // no data
    if (bpm < 8)  return Math.min(100, 80 - bpm * 2);   // low blink = focused/stressed
    if (bpm <= 20) return Math.max(0, (bpm - 8) * 3);    // normal zone
    return Math.min(100, 20 + (bpm - 20) * 4);           // high blink = anxiety
  }
}

window.BlinkDetector = BlinkDetector;
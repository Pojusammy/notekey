/**
 * Real-time pitch detection using the Web Audio API + autocorrelation.
 *
 * This implements the YIN-inspired autocorrelation algorithm for
 * fundamental frequency (F0) estimation — lightweight enough to
 * run in the browser at 60 fps.
 */

export interface PitchResult {
  frequency: number; // Hz, 0 if no pitch detected
  clarity: number; // 0–1 confidence
}

const MIN_FREQUENCY = 60; // ~B1
const MAX_FREQUENCY = 1500; // ~F#6

/**
 * Autocorrelation-based pitch detection.
 * Returns the detected fundamental frequency and a clarity measure.
 */
export function detectPitch(
  buffer: Float32Array,
  sampleRate: number
): PitchResult {
  const bufferSize = buffer.length;

  // Quick energy check — skip silent frames
  let rms = 0;
  for (let i = 0; i < bufferSize; i++) {
    rms += buffer[i] * buffer[i];
  }
  rms = Math.sqrt(rms / bufferSize);
  if (rms < 0.01) {
    return { frequency: 0, clarity: 0 };
  }

  // Autocorrelation
  const minPeriod = Math.floor(sampleRate / MAX_FREQUENCY);
  const maxPeriod = Math.floor(sampleRate / MIN_FREQUENCY);

  let bestCorrelation = -1;
  let bestPeriod = 0;

  for (let period = minPeriod; period <= maxPeriod; period++) {
    let correlation = 0;
    let norm1 = 0;
    let norm2 = 0;

    for (let i = 0; i < bufferSize - period; i++) {
      correlation += buffer[i] * buffer[i + period];
      norm1 += buffer[i] * buffer[i];
      norm2 += buffer[i + period] * buffer[i + period];
    }

    const normalizer = Math.sqrt(norm1 * norm2);
    if (normalizer > 0) {
      correlation /= normalizer;
    }

    if (correlation > bestCorrelation) {
      bestCorrelation = correlation;
      bestPeriod = period;
    }
  }

  if (bestCorrelation < 0.8 || bestPeriod === 0) {
    return { frequency: 0, clarity: bestCorrelation };
  }

  // Parabolic interpolation for sub-sample accuracy
  const prev =
    bestPeriod > minPeriod ? autocorrelationAt(buffer, bestPeriod - 1) : 0;
  const curr = autocorrelationAt(buffer, bestPeriod);
  const next =
    bestPeriod < maxPeriod ? autocorrelationAt(buffer, bestPeriod + 1) : 0;

  const shift = (prev - next) / (2 * (prev - 2 * curr + next));
  const refinedPeriod = bestPeriod + (isFinite(shift) ? shift : 0);

  const frequency = sampleRate / refinedPeriod;

  return {
    frequency,
    clarity: bestCorrelation,
  };
}

function autocorrelationAt(buffer: Float32Array, period: number): number {
  let correlation = 0;
  for (let i = 0; i < buffer.length - period; i++) {
    correlation += buffer[i] * buffer[i + period];
  }
  return correlation;
}

/**
 * Manages the Web Audio API lifecycle for live pitch detection.
 */
export class LivePitchDetector {
  private audioContext: AudioContext | null = null;
  private analyserNode: AnalyserNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private stream: MediaStream | null = null;
  private buffer: Float32Array<ArrayBuffer> | null = null;
  private animationFrame: number | null = null;
  private _isListening = false;

  get isListening(): boolean {
    return this._isListening;
  }

  async start(
    onPitch: (result: PitchResult) => void
  ): Promise<void> {
    if (this._isListening) return;

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });

    this.audioContext = new AudioContext();
    this.analyserNode = this.audioContext.createAnalyser();
    this.analyserNode.fftSize = 4096;

    this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
    this.sourceNode.connect(this.analyserNode);

    this.buffer = new Float32Array(this.analyserNode.fftSize);
    this._isListening = true;

    const tick = () => {
      if (!this._isListening || !this.analyserNode || !this.buffer) return;

      this.analyserNode.getFloatTimeDomainData(this.buffer);
      const result = detectPitch(this.buffer, this.audioContext!.sampleRate);
      onPitch(result);

      this.animationFrame = requestAnimationFrame(tick);
    };

    tick();
  }

  stop(): void {
    this._isListening = false;

    if (this.animationFrame !== null) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }

    this.sourceNode?.disconnect();
    this.sourceNode = null;

    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;

    this.audioContext?.close();
    this.audioContext = null;

    this.analyserNode = null;
    this.buffer = null;
  }
}

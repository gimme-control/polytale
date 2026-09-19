// Client-side WAV encoding: 16 kHz mono 16-bit PCM (what the STT providers accept).

export const TARGET_SAMPLE_RATE = 16000;

/**
 * Downsample float PCM from `inRate` to `outRate` by box-averaging each output
 * window (a cheap low-pass that avoids the worst aliasing of naive decimation).
 */
export function downsample(input: Float32Array, inRate: number, outRate = TARGET_SAMPLE_RATE): Float32Array {
  if (inRate === outRate) return input;
  if (inRate < outRate) {
    // Upsample by linear interpolation (rare: some devices capture at 8 kHz).
    const ratio = inRate / outRate;
    const out = new Float32Array(Math.floor(input.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const pos = i * ratio;
      const i0 = Math.floor(pos);
      const i1 = Math.min(input.length - 1, i0 + 1);
      const f = pos - i0;
      out[i] = input[i0] * (1 - f) + input[i1] * f;
    }
    return out;
  }
  const ratio = inRate / outRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  let pos = 0;
  for (let i = 0; i < out.length; i++) {
    const next = Math.round((i + 1) * ratio);
    let sum = 0;
    let n = 0;
    for (let j = pos; j < next && j < input.length; j++) {
      sum += input[j];
      n++;
    }
    out[i] = n ? sum / n : 0;
    pos = next;
  }
  return out;
}

/** Encode mono float samples in [-1, 1] as a 16-bit PCM RIFF/WAVE blob. */
export function encodeWav(samples: Float32Array, sampleRate = TARGET_SAMPLE_RATE): Blob {
  const bytesPerSample = 2;
  const dataLen = samples.length * bytesPerSample;
  const buf = new ArrayBuffer(44 + dataLen);
  const v = new DataView(buf);
  const str = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i));
  };
  str(0, "RIFF");
  v.setUint32(4, 36 + dataLen, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true); // PCM chunk size
  v.setUint16(20, 1, true); // format = PCM
  v.setUint16(22, 1, true); // channels = mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * bytesPerSample, true); // byte rate
  v.setUint16(32, bytesPerSample, true); // block align
  v.setUint16(34, 16, true); // bits per sample
  str(36, "data");
  v.setUint32(40, dataLen, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++, off += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

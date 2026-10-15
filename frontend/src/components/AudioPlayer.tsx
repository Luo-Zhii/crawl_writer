/**
 * Audio player for chapter narration using CapCut TTS
 */

import { useState } from "react";

interface AudioPlayerProps {
  chapterNumber: number;
  chapterText: string;
  language: "vi" | "zh";
}

export function AudioPlayer({ chapterNumber, chapterText, language }: AudioPlayerProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [selectedVoice, setSelectedVoice] = useState<string>(
    language === "vi" ? "BV421_vivn_streaming" : "BV225_zhcn_streaming"
  );
  const [speed, setSpeed] = useState(1.0);

  const voices = {
    vi: [
      { id: "BV421_vivn_streaming", name: "👩 Female VN" },
      { id: "BV422_vivn_streaming", name: "👨 Male VN" },
    ],
    zh: [
      { id: "BV225_zhcn_streaming", name: "👩 Female Mandarin" },
      { id: "BV226_zhcn_streaming", name: "👨 Male Mandarin" },
    ],
  };

  const generateAudio = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/tts/synthesize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: chapterText.substring(0, 5000), // Limit to 5000 chars
          lang: language,
          voice_id: selectedVoice,
          speed: speed,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to generate audio");
      }

      const data = await response.json();

      // Convert hex audio back to bytes and create blob
      if (data.audio) {
        const binaryString = atob(Buffer.from(data.audio, "hex").toString("base64"));
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: "audio/wav" });
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsLoading(false);
    }
  };

  const styles = {
    container: {
      border: `1px solid var(--border)`,
      borderRadius: "8px",
      padding: "1rem",
      margin: "1rem 0",
      background: "var(--bg-soft)",
    },
    title: {
      fontSize: "1.1rem",
      fontWeight: "600",
      margin: "0 0 1rem 0",
    },
    content: {
      display: "grid",
      gap: "0.8rem",
    },
    field: {
      display: "grid",
      gap: "0.4rem",
    },
    label: {
      fontSize: "0.85rem",
      fontWeight: "500",
      color: "var(--text)",
    },
    select: {
      width: "100%",
    },
    slider: {
      width: "100%",
      padding: "0",
    },
    error: {
      background: "var(--err)",
      color: "white",
      padding: "0.6rem",
      borderRadius: "6px",
      fontSize: "0.85rem",
    },
    button: {
      width: "100%",
      padding: "0.6rem",
      background: "var(--accent)",
      color: "var(--accent-text)",
      border: "1px solid var(--accent)",
      borderRadius: "6px",
      fontWeight: "600",
      fontSize: "0.95rem",
    },
    audioBox: {
      border: `1px solid var(--border)`,
      padding: "0.8rem",
      borderRadius: "6px",
      background: "var(--bg)",
    },
    audio: {
      width: "100%",
    },
    hint: {
      fontSize: "0.75rem",
      color: "var(--text-soft)",
      margin: "0.5rem 0 0 0",
    },
    info: {
      fontSize: "0.75rem",
      color: "var(--text-soft)",
      borderTop: `1px solid var(--border)`,
      paddingTop: "0.6rem",
      margin: "0.6rem 0 0 0",
    },
  };

  return (
    <div style={styles.container}>
      <h3 style={styles.title}>
        🎙️ Nghe Audio - Chương {chapterNumber}
      </h3>

      <div style={styles.content}>
        {/* Voice selector */}
        <div style={styles.field}>
          <label style={styles.label}>Chọn giọng đọc:</label>
          <select
            value={selectedVoice}
            onChange={(e) => setSelectedVoice(e.target.value)}
            style={styles.select}
          >
            {voices[language].map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name}
              </option>
            ))}
          </select>
        </div>

        {/* Speed slider */}
        <div style={styles.field}>
          <label style={styles.label}>
            Tốc độ đọc: {speed.toFixed(1)}x
          </label>
          <input
            type="range"
            min="0.5"
            max="2.0"
            step="0.1"
            value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))}
            style={styles.slider}
          />
        </div>

        {/* Error message */}
        {error && (
          <div style={styles.error}>
            ❌ {error}
          </div>
        )}

        {/* Generate button */}
        <button
          onClick={generateAudio}
          disabled={isLoading}
          style={{
            ...styles.button,
            opacity: isLoading ? 0.6 : 1,
            cursor: isLoading ? "not-allowed" : "pointer",
          }}
        >
          {isLoading ? "⏳ Đang tạo audio..." : "🎬 Tạo Audio"}
        </button>

        {/* Audio player */}
        {audioUrl && (
          <div style={styles.audioBox}>
            <audio
              controls
              src={audioUrl}
              style={styles.audio}
            />
            <p style={styles.hint}>
              💾 Bấm download icon để lưu file audio
            </p>
          </div>
        )}

        {/* Info */}
        <div style={styles.info}>
          <p>📝 Hỗ trợ: Tiếng Việt, Tiếng Trung (Mandarin)</p>
          <p>⚠️ Cần cấu hình CapCut API để dùng tính năng này</p>
        </div>
      </div>
    </div>
  );
}

/**
 * Audio player for chapter narration using CapCut TTS
 */

import { useEffect, useState } from "react";

interface Voice {
  id: string;
  name: string;
  lang: string;
  resource_id: string;
}

interface VoiceResponse {
  lang: string;
  count: number;
  voices: Voice[];
}

interface AudioPlayerProps {
  chapterNumber: number;
  chapterText: string;
  language: "vi" | "zh" | "en" | "ja" | "th" | "es" | "de" | "fr" | "pt" | "id";
}

const LANGUAGE_NAMES: Record<string, string> = {
  "vi-VN": "Tiếng Việt",
  "vi": "Tiếng Việt",
  "zh-CN": "中文",
  "zh": "中文",
  "en-US": "English",
  "en": "English",
  "ja-JP": "日本語",
  "ja": "日本語",
  "th-TH": "ไทย",
  "th": "ไทย",
  "es-ES": "Español",
  "es": "Español",
  "de-DE": "Deutsch",
  "de": "Deutsch",
  "fr-FR": "Français",
  "fr": "Français",
  "pt-BR": "Português",
  "pt": "Português",
  "id-ID": "Bahasa Indonesia",
  "id": "Bahasa Indonesia",
};

export function AudioPlayer({ chapterNumber, chapterText, language }: AudioPlayerProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingVoices, setIsLoadingVoices] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [selectedVoice, setSelectedVoice] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState<string>("");

  const [speed, setSpeed] = useState(1.0);

  // Fetch voices for selected language when component mounts or language changes
  useEffect(() => {
    const fetchVoices = async () => {
      setIsLoadingVoices(true);
      setError(null);
      try {
        const response = await fetch(`/api/tts/voices?lang=${language}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch voices: ${response.statusText}`);
        }
        const data: VoiceResponse = await response.json();
        setVoices(data.voices);
        setSearchTerm(""); // Reset search when language changes
        
        // Set first voice as default
        if (data.voices.length > 0) {
          setSelectedVoice(data.voices[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load voices");
        setVoices([]);
      } finally {
        setIsLoadingVoices(false);
      }
    };

    fetchVoices();
  }, [language]);

  // Filter voices based on search term
  const filteredVoices = voices.filter((voice) =>
    voice.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

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
    langBadge: {
      fontSize: "0.85rem",
      padding: "0.5rem 0.75rem",
      background: "var(--accent)",
      color: "var(--accent-text)",
      borderRadius: "6px",
      fontWeight: "500",
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
    searchInput: {
      width: "100%",
      padding: "0.5rem",
      fontSize: "0.9rem",
      marginBottom: "0.4rem",
    },
    loading: {
      fontSize: "0.85rem",
      color: "var(--text-soft)",
      padding: "0.5rem",
    },
    noVoices: {
      fontSize: "0.85rem",
      color: "var(--warn)",
      padding: "0.5rem",
      background: "rgba(255, 165, 0, 0.1)",
      borderRadius: "4px",
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
        {/* Language info */}
        <div style={styles.langBadge}>
          🌐 {LANGUAGE_NAMES[language] || language.toUpperCase()}
          {isLoadingVoices && " (đang tải giọng...)"}
        </div>

        {/* Voice selector */}
        <div style={styles.field}>
          <label style={styles.label}>
            Chọn giọng đọc ({filteredVoices.length}/{voices.length} giọng)
          </label>
          {isLoadingVoices ? (
            <div style={styles.loading}>⏳ Đang tải danh sách giọng...</div>
          ) : error ? (
            <div style={styles.error}>❌ {error}</div>
          ) : voices.length > 0 ? (
            <>
              {/* Search box */}
              <input
                type="text"
                placeholder="🔍 Tìm kiếm giọng..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={styles.searchInput}
              />
              
              {/* Voice dropdown */}
              <select
                value={selectedVoice}
                onChange={(e) => setSelectedVoice(e.target.value)}
                style={styles.select}
              >
                {filteredVoices.length > 0 ? (
                  filteredVoices.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.name}
                    </option>
                  ))
                ) : (
                  <option disabled>Không tìm thấy giọng phù hợp</option>
                )}
              </select>
              
              {/* Show all/filtered info */}
              {searchTerm && filteredVoices.length === 0 && (
                <div style={styles.noVoices}>
                  ⚠️ Không tìm thấy giọng: "{searchTerm}"
                </div>
              )}
            </>
          ) : (
            <div style={styles.noVoices}>
              ⚠️ Không có giọng nào cho ngôn ngữ này
            </div>
          )}
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

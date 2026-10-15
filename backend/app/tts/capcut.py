"""CapCut TTS integration for chapter audio narration."""

import asyncio
import json
from typing import Optional
from pathlib import Path

try:
    import requests
    from capcut_tts_api import CapCutClient
    HAS_CAPCUT = True
except ImportError:
    HAS_CAPCUT = False

# Hardcoded voice catalog from CapCut SDK (from Voice.json)
VOICE_CATALOG = {
    "vi-VN": [
        {"voice_type": "BV421_vivn_streaming", "display_name": "Nhỏ Ngọt Ngào", "lang": "vi"},
        {"voice_type": "vi_female_huong", "display_name": "Giọng Nữ Phổ Thông", "lang": "vi"},
        {"voice_type": "BV074_streaming_dsp", "display_name": "Giọng Bé", "lang": "vi"},
        {"voice_type": "BV074_streaming", "display_name": "Cô Gái Hoạt Ngôn", "lang": "vi"},
        {"voice_type": "vi-VN-HoaiMyNeural", "display_name": "Hoai My", "lang": "vi"},
        {"voice_type": "vi-VN-NamMinhNeural", "display_name": "Nam Minh", "lang": "vi"},
        {"voice_type": "BV075_streaming_vibrato_dsp", "display_name": "Việt Méo", "lang": "vi"},
        {"voice_type": "BV562_streaming", "display_name": "Mai", "lang": "vi"},
        {"voice_type": "multi_female_yangguangnv_uranus_bigtts", "display_name": "Ban Mai", "lang": "vi"},
        {"voice_type": "multi_female_richgirl_uranus_bigtts", "display_name": "Review Phim new", "lang": "vi"},
        {"voice_type": "multi_female_quanweinv_uranus_bigtts", "display_name": "Bản Tin 1", "lang": "vi"},
        {"voice_type": "multi_female_stokie_uranus_bigtts", "display_name": "Review Phim 4", "lang": "vi"},
        {"voice_type": "multi_female_sisi_uranus_bigtts", "display_name": "Bản Tin nữ", "lang": "vi"},
        {"voice_type": "multi_female_daqi_uranus_bigtts", "display_name": "Review Phim 3", "lang": "vi"},
        {"voice_type": "multi_female_xyf04auto_uranus_bigtts", "display_name": "Review Phim 2", "lang": "vi"},
        {"voice_type": "multi_female_kiwi_uranus_bigtts", "display_name": "Sunny Idol", "lang": "vi"},
        {"voice_type": "BV075_streaming_demon_dsp", "display_name": "Kenny Đại Đế", "lang": "vi"},
        {"voice_type": "BV075_streaming_robot_dsp", "display_name": "Robot VN", "lang": "vi"},
        {"voice_type": "multi_male_felipe_uranus_bigtts", "display_name": "Giọng Nam Trầm", "lang": "vi"},
        {"voice_type": "multi_female_peiqi_uranus_bigtts", "display_name": "Giọng Gái Mới Lớn", "lang": "vi"},
        {"voice_type": "multi_female_xinwenjieshuo_uranus_bigtts", "display_name": "Nam bản tin", "lang": "vi"},
        {"voice_type": "multi_female_tianmeijieshuo_uranus_bigtts", "display_name": "Quên Tên Tự Test", "lang": "vi"},
        {"voice_type": "BV075_streaming", "display_name": "Thanh Niên Tự Tin", "lang": "vi"},
    ],
    "zh-CN": [
        {"voice_type": "BV452_streaming", "display_name": "Vũ hán", "lang": "zh"},
        {"voice_type": "zh_female_xiaonan_lv_clone2", "display_name": "旅遊主播", "lang": "zh"},
        {"voice_type": "BV433_streaming", "display_name": "電視廣告", "lang": "zh"},
        {"voice_type": "BV213_streaming", "display_name": "Dramaaa", "lang": "zh"},
        {"voice_type": "zh_female_guaiqiaogirl", "display_name": "Guaiqiaogirl", "lang": "zh"},
        {"voice_type": "zh_male_tangsengdsp", "display_name": "Tangsengdsp", "lang": "zh"},
        {"voice_type": "zh_female_naying", "display_name": "Naying", "lang": "zh"},
        {"voice_type": "multi_male_M092_conversation_wvae_bigtts_cc", "display_name": "conversation", "lang": "zh"},
        {"voice_type": "DiT_zh_male_xionger", "display_name": "XiaoChao", "lang": "zh"},
        {"voice_type": "zh_female_xiaoyue", "display_name": "Xiaoyue", "lang": "zh"},
        {"voice_type": "zh_female_angela", "display_name": "暗夜蘿莉", "lang": "zh"},
        {"voice_type": "multi_zh_male_youyoujunzi_moon_bigtts_cc", "display_name": "Rizki", "lang": "zh"},
        {"voice_type": "zh_female_inspirational", "display_name": "溫柔姐姐", "lang": "zh"},
        {"voice_type": "zh_female_sistermango", "display_name": "語音助理", "lang": "zh"},
        {"voice_type": "DiT_zh_male_paoxiaoge", "display_name": "paoxiaoge", "lang": "zh"},
    ],
    "en-US": [
        {"voice_type": "en_us_006", "display_name": "EN US 2", "lang": "en"},
        {"voice_type": "en_us_002", "display_name": "EN US", "lang": "en"},
        {"voice_type": "en_female_janeamber_mars_bigtts", "display_name": "Janeamber", "lang": "en"},
        {"voice_type": "en_female_emotional_moon_bigtts", "display_name": "Emotional", "lang": "en"},
        {"voice_type": "BV510_streaming", "display_name": "English", "lang": "en"},
        {"voice_type": "en_female_sherry", "display_name": "Sherry", "lang": "en"},
        {"voice_type": "en_us_010", "display_name": "Chrming Male", "lang": "en"},
        {"voice_type": "en_male_deadpool", "display_name": "Deadpool", "lang": "en"},
        {"voice_type": "en-US-JennyMultilingualNeural", "display_name": "Jenny", "lang": "en"},
        {"voice_type": "en", "display_name": "Male Eng", "lang": "en"},
        {"voice_type": "en_male_m03_classical", "display_name": "Classical Music", "lang": "en"},
        {"voice_type": "en_male_dramaqueen_zachk", "display_name": "Dramaaa", "lang": "en"},
        {"voice_type": "BV503_streaming", "display_name": "Energetic Famale", "lang": "en"},
        {"voice_type": "en_female_nail_artist", "display_name": "Artist", "lang": "en"},
        {"voice_type": "ICL_en_female_little_cute_dsp", "display_name": "Cute Girl", "lang": "en"},
        {"voice_type": "en_male_trickster_stream", "display_name": "Trickster", "lang": "en"},
        {"voice_type": "en_male_artistic_layne", "display_name": "Mentor", "lang": "en"},
        {"voice_type": "en_male_death_rock", "display_name": "Grim Rock", "lang": "en"},
        {"voice_type": "ICL_en_male_philosopher_dsp", "display_name": "Narrator", "lang": "en"},
        {"voice_type": "en_us_007", "display_name": "Male Profess", "lang": "en"},
        {"voice_type": "ICL_en_female_ditie_dsp", "display_name": "Creepy female", "lang": "en"},
        {"voice_type": "en_female_soothing_mars_bigtts", "display_name": "Female Teacher", "lang": "en"},
        {"voice_type": "BV072_streaming", "display_name": "Suaraaa", "lang": "en"},
        {"voice_type": "DiT_en_female_jessie", "display_name": "Jessie", "lang": "en"},
        {"voice_type": "BV540_streaming", "display_name": "Desti", "lang": "en"},
        {"voice_type": "en_female_loba_apex", "display_name": "Robaa", "lang": "en"},
        {"voice_type": "DiT_en_male_trickster", "display_name": "Trickster", "lang": "en"},
        {"voice_type": "en_female_caroline_clone2", "display_name": "Excited", "lang": "en"},
        {"voice_type": "ICL_en_male_305M_JamieTr", "display_name": "Tinn", "lang": "en"},
        {"voice_type": "ICL_en_male_kevin2", "display_name": "Mischief", "lang": "en"},
        {"voice_type": "en_us_002_dsp", "display_name": "Dolly famle", "lang": "en"},
        {"voice_type": "BV507_streaming", "display_name": "Cute Boy", "lang": "en"},
        {"voice_type": "BV029_streaming", "display_name": "American Female", "lang": "en"},
        {"voice_type": "ICL_en_female_cc_bluetooth", "display_name": "Bluetooth", "lang": "en"},
        {"voice_type": "ICL_en_female_lisa", "display_name": "Lisa", "lang": "en"},
        {"voice_type": "ICL_en_male_317M_BrianJW", "display_name": "BrianJW", "lang": "en"},
        {"voice_type": "ICL_en_male_310M_CoreyK", "display_name": "Kai", "lang": "en"},
        {"voice_type": "ICL_en_male_captain", "display_name": "Captain", "lang": "en"},
        {"voice_type": "multi_female_wenjingmaomao_moon_bigtts_cc", "display_name": "Daiana", "lang": "en"},
        {"voice_type": "ICL_en_male_oogie2", "display_name": "Oogie", "lang": "en"},
    ],
}


class CapcutTTSService:
    """Text-to-speech using CapCut API."""

    def __init__(self):
        self.client: Optional[CapCutClient] = None
        self._init_client()

    def _init_client(self):
        """Initialize CapCut client if available."""
        if not HAS_CAPCUT:
            return

        try:
            # Try to load device config from home directory
            device_path = Path.home() / ".capcut" / "device.json"
            if device_path.exists():
                with open(device_path) as f:
                    device_config = json.load(f)
                self.client = CapCutClient(device_config)
            else:
                # Create a client without auth just for voice catalog (no auth needed for that)
                self.client = CapCutClient()
        except Exception as e:
            print(f"⚠️ CapCut TTS unavailable: {e}")

    async def synthesize(
        self,
        text: str,
        lang: str = "vi",
        voice_id: str = "BV421_vivn_streaming",
        speed: float = 1.0,
    ) -> Optional[bytes]:
        """
        Synthesize text to audio using CapCut TTS.

        Args:
            text: Text to synthesize
            lang: Language code ('vi' for Vietnamese, 'zh' for Mandarin)
            voice_id: CapCut voice ID (voice_type)
            speed: Speech speed (0.5-2.0)

        Returns:
            Audio bytes (WAV format) or None if synthesis fails
        """
        if not self.client:
            return None

        if not text or len(text) > 5000:
            return None

        try:
            loop = asyncio.get_event_loop()
            audio_data = await loop.run_in_executor(
                None,
                lambda: self.client.generate_speech(
                    texts=text,
                    voice=voice_id,
                    rate=str(speed),
                    wait=True
                ),
            )
            return audio_data
        except Exception as e:
            print(f"❌ TTS synthesis failed: {e}")
            return None

    def list_voices(self, lang: str = "vi") -> list[dict]:
        """
        List available voices for a language.
        
        Returns voices from hardcoded catalog (from CapCut SDK Voice.json).
        Voices include display name, voice type, and lang code.
        """
        # Map shorthand lang codes to full locale codes
        lang_map = {
            "vi": "vi-VN",
            "zh": "zh-CN",
            "en": "en-US",
            "ja": "ja-JP",
            "th": "th-TH",
            "es": "es-ES",
            "de": "de-DE",
            "fr": "fr-FR",
            "pt": "pt-BR",
            "id": "id-ID",
        }
        
        full_lang = lang_map.get(lang, f"{lang}-{lang.upper()}")
        voices = VOICE_CATALOG.get(full_lang, [])
        
        # Convert to dict format for API response
        return [
            {
                "id": v["voice_type"],
                "name": v["display_name"],
                "lang": v["lang"],
                "resource_id": v.get("resource_id", ""),
            }
            for v in voices
        ]

    def is_available(self) -> bool:
        """Check if CapCut TTS is configured and available."""
        return self.client is not None


# Global instance
tts_service = CapcutTTSService()

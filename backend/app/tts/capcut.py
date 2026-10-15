"""CapCut TTS integration for chapter audio narration."""

import asyncio
import json
from typing import Optional
from pathlib import Path

try:
    import requests
    from capcut_tts_api import ClientConfig, CapcutAPIClient
    HAS_CAPCUT = True
except ImportError:
    HAS_CAPCUT = False


VOICES = {
    "vi": [
        {"id": "BV421_vivn_streaming", "name": "BV421 Vietnamese", "gender": "female"},
        {"id": "BV422_vivn_streaming", "name": "BV422 Vietnamese", "gender": "male"},
    ],
    "zh": [
        {"id": "BV225_zhcn_streaming", "name": "BV225 Mandarin", "gender": "female"},
        {"id": "BV226_zhcn_streaming", "name": "BV226 Mandarin", "gender": "male"},
    ],
}


class CapcutTTSService:
    """Text-to-speech using CapCut API."""

    def __init__(self):
        self.client: Optional[CapcutAPIClient] = None
        self._init_client()

    def _init_client(self):
        """Initialize CapCut client if available."""
        if not HAS_CAPCUT:
            return

        try:
            # Load device config from environment or file
            device_path = Path.home() / ".capcut" / "device.json"
            if device_path.exists():
                with open(device_path) as f:
                    device_config = json.load(f)
                self.client = CapcutAPIClient(device_config)
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
            voice_id: CapCut voice ID
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
                lambda: self.client.synthesize(
                    text=text,
                    voice_type=voice_id,
                    speed=speed,
                ),
            )
            return audio_data
        except Exception as e:
            print(f"❌ TTS synthesis failed: {e}")
            return None

    def list_voices(self, lang: str = "vi") -> list[dict]:
        """List available voices for a language."""
        return VOICES.get(lang, [])

    def is_available(self) -> bool:
        """Check if CapCut TTS is configured and available."""
        return self.client is not None


# Global instance
tts_service = CapcutTTSService()

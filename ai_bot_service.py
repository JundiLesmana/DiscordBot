import os
import time
import asyncio
import logging
import requests
import hashlib
import google.generativeai as genai
from typing import Optional
from urllib.parse import quote_plus

class SmartAIService:
    def __init__(self):
        self.wolfram_id = os.getenv("WOLFRAM_APP_ID")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.hf_token = os.getenv("HF_TOKEN")
        self.response_cache = {}
        self.CACHE_DURATION = 300

        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)

    async def get_response(self, user_prompt: str, user_id: int, image_bytes: Optional[bytes] = None):
        """
        Router pintar: pilih AI sesuai konteks.
        image_bytes: Jika ada, gunakan untuk OCR atau analisis gambar (bukan URL).
        """
        cache_key_prompt = (user_prompt or "")[:50]
        if image_bytes:
            image_hash = hashlib.md5(image_bytes).hexdigest()[:8]
            cache_key_prompt += f"_img_{image_hash}"

        key = f"{user_id}_{cache_key_prompt}"

        cached = self.response_cache.get(key)
        if cached and time.time() - cached['t'] < self.CACHE_DURATION:
            return cached['r']

        prompt_lower = (user_prompt or "").lower()
        try:
            if image_bytes and self._is_ocr_request(user_prompt):
                result = await asyncio.to_thread(self._ocr_with_gemini, image_bytes, user_prompt)
            elif any(k in prompt_lower for k in ["integral", "matrix", "logika", "fungsi", "persamaan", "sin", "cos", "limit"]):
                result = await asyncio.to_thread(self._wolfram_query, user_prompt)
            elif any(k in prompt_lower for k in ["code", "python", "javascript", "error", "bug", "function", "script", "compile"]):
                result = await asyncio.to_thread(self._codegemma_query, user_prompt)
            else:
                result = await asyncio.to_thread(self._gemini_query, user_prompt)
        except Exception as e:
            result = f"❌ Internal routing error: {e}"

        self.response_cache[key] = {'r': result, 't': time.time()}
        return result

    def _is_ocr_request(self, prompt: str) -> bool:
        """Memeriksa apakah permintaan pengguna adalah OCR."""
        ocr_keywords = ["text dari gambar", "baca teks", "teks di gambar", "ocr", "extract text", "text extraction", "baca gambar"]
        return any(k in (prompt or "").lower() for k in ocr_keywords)

    def _ocr_with_gemini(self, image_bytes: bytes, prompt: str):
        """Menggunakan Gemini untuk OCR dari image bytes."""
        try:
            model = genai.GenerativeModel("models/gemini-2.5-flash")

            if not prompt or self._is_ocr_request(prompt):
                prompt = "Tolong ekstrak semua teks yang terlihat di gambar atau dokumen ini. Jika ada bagian yang tidak bisa dibaca atau tidak ada teks, beri tahu saya."

            result = model.generate_content(
                [prompt, image_bytes],
                generation_config=genai.types.GenerationConfig(
                    candidate_count=1,
                    max_output_tokens=1024,
                ),
            )
            return getattr(result, "text", str(result))
        except Exception as e:
            logging.exception("OCR (Gemini) failure")
            return f"❌ OCR (Gemini) Error: {e}"

    def _wolfram_query(self, q: str):
        try:
            if not self.wolfram_id:
                return "❌ Wolfram App ID tidak diset."

            encoded = quote_plus(q or "")
            url = f"https://api.wolframalpha.com/v2/query?input={encoded}&appid={self.wolfram_id}&output=json"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            pods = r.json().get("queryresult", {}).get("pods", [])
            output = []
            for p in pods:
                sub = p.get("subpods", [])
                text = sub[0].get("plaintext") if sub else None
                if text:
                    output.append(f"**{p.get('title','')}**: {text}")
            return "\n".join(output) if output else "❌ Wolfram returned no plaintext pods."
        except Exception as e:
            logging.exception("Wolfram query failure")
            return f"❌ Wolfram Error: {e}"

    def _codegemma_query(self, prompt: str):
        try:
            if not self.hf_token:
                return "❌ HF token tidak diset."
            url = "https://router.huggingface.co/hf-inference/models/google/codegemma-7b"
            headers = {"Authorization": f"Bearer {self.hf_token}"}
            payload = {"inputs": prompt, "parameters": {"max_new_tokens": 512}}
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            # coba beberapa bentuk respons
            if isinstance(data, list) and data:
                return data[0].get("generated_text", str(data[0]))
            if isinstance(data, dict):
                return data.get("generated_text") or data.get("text") or str(data)
            return str(data)
        except Exception as e:
            logging.exception("CodeGemma query failure")
            return f"❌ CodeGemma Error: {e}"
        
    def _gemini_query(self, text: str):
        try:
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            resp = model.generate_content([text])
            return getattr(resp, "text", str(resp))
        except Exception as e:
            logging.exception("Gemini query failure")
            return f"❌ Gemini Error: {e}"

ai_bot_services = SmartAIService()
import os
import time
import asyncio
import logging
import requests
import google.generativeai as genai
from typing import Optional

class SmartAIService:
    def __init__(self):
        # self.ocr_api = os.getenv("OCR_API_KEY")  # Removed OCR.SPACE
        self.wolfram_id = os.getenv("WOLFRAM_APP_ID")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.hf_token = os.getenv("HF_TOKEN")
        self.response_cache = {}
        self.CACHE_DURATION = 300

        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)

    async def get_response(self, user_prompt: str, user_id: int, image_url: Optional[str] = None):
        """
        Router pintar: pilih AI sesuai konteks.
        image_url: Jika ada, gunakan untuk OCR atau analisis gambar.
        """
        # Key cache bisa disesuaikan jika image_url ada
        cache_key_prompt = user_prompt[:50]
        if image_url:
            cache_key_prompt += f"_{hash(image_url) % 10000}" # Singkatkan URL menjadi hash
        key = f"{user_id}_{cache_key_prompt}"

        if key in self.response_cache and time.time() - self.response_cache[key]['t'] < self.CACHE_DURATION:
            return self.response_cache[key]['r']

        # Jika ada gambar dan prompt terkait OCR
        if image_url and self._is_ocr_request(user_prompt):
            result = self._ocr_with_gemini(image_url, user_prompt)
        elif any(k in user_prompt.lower() for k in ["integral", "matrix", "logika", "fungsi", "persamaan", "sin", "cos", "limit"]):
            result = self._wolfram_query(user_prompt)
        elif any(k in user_prompt.lower() for k in ["code", "python", "javascript", "error", "bug", "function", "script", "compile"]):
            result = self._codegemma_query(user_prompt)
        else:
            result = self._gemini_query(user_prompt)

        self.response_cache[key] = {'r': result, 't': time.time()}
        return result

    def _is_ocr_request(self, prompt: str) -> bool:
        """Memeriksa apakah permintaan pengguna adalah OCR."""
        ocr_keywords = ["text dari gambar", "baca teks", "teks di gambar", "ocr", "extract text", "text extraction", "baca gambar"]
        return any(k in prompt.lower() for k in ocr_keywords)

    def _ocr_with_gemini(self, image_url: str, prompt: str):
        """Menggunakan Gemini untuk OCR dari gambar."""
        try:
            # Download gambar
            response = requests.get(image_url)
            response.raise_for_status()
            image_data = response.content

            # Inisialisasi model
            model = genai.GenerativeModel("models/gemini-2.5-flash")

            # Prompt default jika pengguna tidak memberikan konteks
            if not prompt or self._is_ocr_request(prompt):
                 # Prompt yang lebih umum dan netral
                prompt = "Tolong ekstrak semua teks yang terlihat di gambar atau dokumen ini. Jika ada bagian yang tidak bisa dibaca atau tidak ada teks, beri tahu saya."

            # Generate content dengan gambar
            result = model.generate_content(
                [prompt, image_data],
                generation_config=genai.types.GenerationConfig(
                    candidate_count=1,
                    max_output_tokens=1024, # Sesuaikan jika perlu
                ),
            )
            return result.text
        except Exception as e:
            return f"❌ OCR (Gemini) Error: {e}"

    def _wolfram_query(self, q):
        try:
            url = f"https://api.wolframalpha.com/v2/query?input={q}&appid={self.wolfram_id}&output=json"
            r = requests.get(url)
            pods = r.json().get("queryresult", {}).get("pods", [])
            return "\n".join(f"**{p['title']}**: {p['subpods'][0]['plaintext']}" for p in pods if p["subpods"][0].get("plaintext"))
        except Exception as e:
            return f"❌ Wolfram Error: {e}"

    def _codegemma_query(self, prompt):
        try:
            url = "https://router.huggingface.co/hf-inference/models/google/codegemma-7b"
            headers = {"Authorization": f"Bearer {self.hf_token}"}
            payload = {"inputs": prompt, "parameters": {"max_new_tokens": 512}}
            r = requests.post(url, headers=headers, json=payload)
            return r.json()[0]["generated_text"]
        except Exception as e:
            return f"❌ CodeGemma Error: {e}"
        
    def _gemini_query(self, text):
        try:
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            resp = model.generate_content(text)
            return resp.text
        except Exception as e:
            return f"❌ Gemini Error: {e}"

ai_bot_service = SmartAIService()
import os
import time
import asyncio
from groq import Groq

class GroqService:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("❌ GROQ_API_KEY harus diisi di .env")
        self.client = Groq(api_key=self.api_key)
        self.response_cache = {}
        self.CACHE_DURATION = 300  # 5 menit

        def _get_smart_prompt(self) -> str: 
            return """Kamu adalah Techfour, asisten AI untuk kelas Teknik Informatika 01TPLE004 (Unpam). 
        Jawab dalam bahasa Indonesia santai seperti teman sekelas.

        📅 JADWAL OKTOBER 2025:
        - E-Learning (20-26 Okt): Logika Informatika P10, Fisika Dasar P10, Agama P7, Pancasila P7
        - Offline (20-26 Okt): Alpro P10, Kalkulus P10, Basic English P7, Pengantar Tekno P7
        - Ujian Online (27 Okt–1 Nov): Pancasila, Agama, Logika, Fisika
        - Ujian Offline (1 Nov): Kalkulus, Alpro, English, Pengantar Tekno

        🎯 ATURAN:
        1. Untuk UJIAN → beri jadwal ujian resmi
        2. Untuk E-LEARNING → beri jadwal e-learning
        3. Untuk AKADEMIK (Kalkulus, Fisika, dll) → beri rumus & penjelasan akurat
        4. Untuk PROGRAMMING → beri contoh code working
        5. Gunakan format rapi: poin-poin, bold istilah, code block untuk code

        Jawab relevan, praktis, dan helpful!"""
    
    async def get_response(self, user_prompt: str, user_id: int) -> str | None:
        cache_key = f"{user_id}_{user_prompt[:50]}"
        if cache_key in self.response_cache:
            cached_data = self.response_cache[cache_key]
            if time.time() - cached_data['timestamp'] < self.CACHE_DURATION:
                return cached_data['response']
        
        try:
            # Jalankan Groq di thread karena library sync
            chat_completion = await asyncio.to_thread(
                self.client.chat.completions.create,
                messages=[
                    {"role": "system", "content": self._get_smart_prompt()},
                    {"role": "user", "content": user_prompt}
                ],
                model="llama-3.1-8b-instant",  
                temperature=0.7,
                max_tokens=2000,
                timeout=15
            )
            reply = chat_completion.choices[0].message.content.strip()
            self.response_cache[cache_key] = {
                'response': reply,
                'timestamp': time.time()
            }
            return reply
        except Exception as e:
            print(f"❌ Groq error: {e}")
            return None

    def clean_old_cache(self):
        current_time = time.time()
        expired_keys = [
            key for key, data in self.response_cache.items()
            if current_time - data['timestamp'] > self.CACHE_DURATION
        ]
        for key in expired_keys:
            del self.response_cache[key]


groq_service = GroqService()
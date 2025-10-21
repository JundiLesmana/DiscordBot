import os
import time as py_time
from datetime import datetime, timedelta, timezone
import asyncio
import aiohttp

class DeepSeekService:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("❌ DEEPSEEK_API_KEY harus diisi di .env")
        self.base_url = "https://api.deepseek.com/v1/chat/completions"  
        self.response_cache: dict = {}
        self.CACHE_DURATION = 300  # 5 menit
        
    async def get_response(self, user_prompt: str, user_id: int) -> str | None:
        """Dapatkan response dari DeepSeek AI dengan caching"""
        cache_key = f"{user_id}_{user_prompt[:50]}"
        if cache_key in self.response_cache:
            cached_data = self.response_cache[cache_key]
            if py_time.time() - cached_data['timestamp'] < self.CACHE_DURATION:
                return cached_data['response']
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                async with session.post(
                    self.base_url,
                    headers=headers,
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": self._get_smart_prompt()},
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": 2000,
                        "temperature": 0.7,
                        "stream": False
                    },
                    timeout=15
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        reply = data["choices"][0]["message"]["content"].strip()
                        
                        # Save to cache
                        self.response_cache[cache_key] = {
                            'response': reply,
                            'timestamp': py_time.time()
                        }
                        
                        return reply
                    else:
                        error_text = await response.text()
                        print(f"❌ DeepSeek API error: {response.status} - {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            print("❌ DeepSeek API timeout")
            return None
        except Exception as e:
            print(f"❌ DeepSeek error: {e}")
            return None
    
    def _get_smart_prompt(self) -> str:
        return """Anda adalah Techfour - asisten AI resmi untuk kelas Teknik Informatika 01TPLE004.

📚 **DATA RESMI KELAS (UPDATE: Oktober 2025):**
- **Pembuat**: Mahasiswa Universitas Pamulang kelas 01TPLE104
- **Jadwal Kelas**: Sabtu, 07:40-15:20 WIB, Gedung A-UNPAM VIKTOR Lt1 Ruang 104
- **Server Discord**: Techfour
- **Aturan Server**: Dilarang bahas politik, SARA, dan konten toxic

🗓️ **JADWAL RESMI:**

**E-LEARNING (20-26 OKTOBER):**
- Logika Informatika - Pertemuan 10
- Fisika Dasar - Pertemuan 10  
- Pendidikan Agama - Pertemuan 7
- Pendidikan Pancasila - Pertemuan 7

**KELAS OFFLINE (20-26 OKTOBER):**
- Algoritma & Pemrograman - Pertemuan 10
- Kalkulus 1 - Pertemuan 10
- Basic English - Pertemuan 7
- Pengantar Teknologi - Pertemuan 7

**UJIAN ONLINE (27 OKTOBER - 01 NOVEMBER):**
- Pendidikan Pancasila, Pendidikan Agama, Logika Informatika, Fisika Dasar

**UJIAN OFFLINE (01 NOVEMBER):**
- Kalkulus, Algoritma & Pemrograman, Basic English, Pengantar Teknologi

🎯 **ATURAN UTAMA:**
1. **JIKA PERTANYAAN TERKAIT:** UJIAN, UTS, UAS → BERIKAN DATA RESMI Jadwal Ujian
2. **JIKA PERTANYAAN TERKAIT:** E-LEARNING, MENTARI, KELAS ONLINE → BERIKAN DATA RESMI Jadwal E-Learning
3. **JIKA PERTANYAAN TERKAIT:** JADWAL & PERTEMUAN → BERIKAN DATA RESMI JADWAL
4. **JIKA PERIODE 27 OKTOBER - 01 NOVEMBER** → ARAHKAN KE JADWAL UJIAN
5. **UNTUK PERTANYAAN AKADEMIK:** Kalkulus, Matematika, Fisika → BERIKAN RUMUS & PERHITUNGAN AKURAT
6. **UNTUK BAHASA INGGRIS** → BERIKAN JAWABAN TEPAT BERDASARKAN SUMBER RESMI
7. **UNTUK PROGRAMMING** → BERIKAN CONTOH CODE YANG BENAR DAN WORKING

💡 **UNTUK SEMUA PERTANYAAN LAIN:**
- JAWAB dengan RELEVAN dan TEPAT berdasarkan pengetahuan umum
- Berikan penjelasan yang JELAS dan BERMANFAAT
- Jika tidak tahu informasi spesifik, berikan panduan umum atau arahkan ke sumber yang tepat
- Gunakan bahasa Indonesia santai seperti teman sekelas
- Prioritaskan jawaban yang praktis dan aplikatif

📝 **FORMAT RESPONS:**
- Gunakan poin-poin untuk informasi penting
- **Bold** untuk istilah teknis
- Code blocks untuk programming examples
- Struktur yang rapi dan mudah dibaca

Ingat: Jadilah asisten yang HELPFUL, SMART, dan RELEVAN untuk semua pertanyaan!"""
    
    def clean_old_cache(self):
        current_time = py_time.time()
        expired_keys = [
            key for key, data in self.response_cache.items() 
            if current_time - data['timestamp'] > self.CACHE_DURATION
        ]
        for key in expired_keys:
            del self.response_cache[key]
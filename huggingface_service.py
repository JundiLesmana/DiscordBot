# huggingface_service.py
import os
import time
import asyncio
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from huggingface_hub import login

class HuggingFaceService:
    def __init__(self):
        
        self.model_name = "meta-llama/Meta-Llama-3.1-8B-Instruct"
        self.tokenizer = None
        self.model = None
        self.pipeline = None
        self.response_cache = {}
        self.CACHE_DURATION = 300  # 5 menit
        self._initialize_model()

    def _initialize_model(self):
        """Initialize model dengan optimasi memory"""
        try:
            print("🔄 Loading Hugging Face model...")
            
            # OPTION 1: Gunakan pipeline (lebih mudah)
            self.pipeline = pipeline(
                "text-generation",
                model=self.model_name,
                torch_dtype=torch.float16,
                device_map="auto",
                model_kwargs={
                    "load_in_8bit": True,  # Menghemat memory
                    "low_cpu_mem_usage": True
                }
            )
            
            # Simpan tokenizer dari pipeline
            self.tokenizer = self.pipeline.tokenizer
            
            print("✅ Model loaded successfully!")
            
        except Exception as e:
            print(f"❌ Error loading model: {e}")
            # Fallback ke model yang lebih ringan
            self._load_fallback_model()

    def _load_fallback_model(self):
        """Fallback ke model yang lebih ringan jika utama gagal"""
        try:
            print("🔄 Loading fallback model...")
            self.model_name = "microsoft/DialoGPT-large"
            self.pipeline = pipeline(
                "text-generation",
                model=self.model_name,
                device_map="auto"
            )
            self.tokenizer = self.pipeline.tokenizer
            print("✅ Fallback model loaded!")
        except Exception as e:
            print(f"❌ Fallback juga gagal: {e}")

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
5. **UNTUK PERTANYAAN MATERI ATAU MATA KULIAH:** Kalkulus, Matematika, Fisika → BERIKAN RUMUS & PERHITUNGAN AKURAT SERTAKAN CONTOH BESERTA IMPLEMENTASI CARA-CARANYA LALU KAMU BISA 
6. **UNTUK BAHASA INGGRIS** → BERIKAN JAWABAN TEPAT BERDASARKAN SUMBER RESMI
7. **UNTUK PROGRAMMING** → BERIKAN CONTOH CODE YANG TEPAT DAN WORKING JANGAN NGASAL NGASIH CODE

💡 **UNTUK SEMUA PERTANYAAN LAIN:**
- JAWAB dengan RELEVAN dan TEPAT berdasarkan pengetahuan umum dan internet
- Berikan penjelasan yang JELAS dan BERMANFAAT
- Jika tidak tahu informasi spesifik, berikan panduan umum atau arahkan ke sumber yang tepat dari internet atau referensi youtube
- Gunakan bahasa Indonesia santai seperti teman sekelas
- Prioritaskan jawaban yang praktis dan aplikatif

📝 **FORMAT RESPONS:**
- Gunakan poin-poin untuk informasi penting
- **Bold** untuk istilah teknis
- Code blocks untuk programming examples
- Struktur yang rapi dan mudah dibaca

Ingat: Jadilah asisten yang GENIUS, PINTAR, dan RELEVAN untuk semua pertanyaan!"""

    def _enhance_prompt(self, user_prompt: str) -> str:
        """Tingkatkan prompt pendek untuk mendapatkan response yang lebih baik"""
        words_count = len(user_prompt.split())
        
        if words_count <= 3:
            return f"{user_prompt}\n\nTolong berikan penjelasan yang detail, lengkap, dan mudah dipahami."
        elif words_count <= 10:
            return f"{user_prompt}\n\nBerikan penjelasan yang komprehensif dengan contoh jika diperlukan."
        else:
            return user_prompt

    async def get_response(self, user_prompt: str, user_id: int) -> str | None:
        cache_key = f"{user_id}_{user_prompt[:50]}"
        
        # Check cache
        if cache_key in self.response_cache:
            cached_data = self.response_cache[cache_key]
            if time.time() - cached_data['timestamp'] < self.CACHE_DURATION:
                print("✅ Menggunakan cached response")
                return cached_data['response']
        
        try:
            # Enhance prompt untuk response yang lebih baik
            enhanced_prompt = self._enhance_prompt(user_prompt)
            
            # Gabungkan system prompt dengan user prompt
            full_prompt = f"{self._get_smart_prompt()}\n\nUser: {enhanced_prompt}\nAssistant:"
            
            # Generate response
            if self.pipeline:
                response = await asyncio.to_thread(
                    self._generate_with_pipeline,
                    full_prompt
                )
            else:
                response = await asyncio.to_thread(
                    self._generate_with_model,
                    full_prompt
                )
            
            if response:
                # Simpan ke cache
                self.response_cache[cache_key] = {
                    'response': response,
                    'timestamp': time.time()
                }
                return response
            else:
                return "❌ Maaf, sedang ada gangguan teknis. Silakan coba lagi."
                
        except Exception as e:
            print(f"❌ HuggingFace error: {e}")
            return None

    def _generate_with_pipeline(self, prompt: str) -> str:
        """Generate menggunakan pipeline"""
        try:
            response = self.pipeline(
                prompt,
                max_new_tokens=4000,  # 2x lebih banyak dari Groq!
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                repetition_penalty=1.1,
                pad_token_id=self.tokenizer.eos_token_id,
                truncation=True
            )
            
            generated_text = response[0]['generated_text']
            # Extract hanya bagian assistant response
            if "Assistant:" in generated_text:
                return generated_text.split("Assistant:")[-1].strip()
            else:
                return generated_text.replace(prompt, "").strip()
                
        except Exception as e:
            print(f"❌ Pipeline generation error: {e}")
            return ""

    def _generate_with_model(self, prompt: str) -> str:
        """Generate menggunakan model langsung (fallback)"""
        try:
            inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=2000,
                    temperature=0.7,
                    do_sample=True,
                    top_p=0.9,
                    repetition_penalty=1.1,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return response.replace(prompt, "").strip()
            
        except Exception as e:
            print(f"❌ Model generation error: {e}")
            return ""

    def clean_old_cache(self):
        """Bersihkan cache yang expired"""
        current_time = time.time()
        expired_keys = [
            key for key, data in self.response_cache.items()
            if current_time - data['timestamp'] > self.CACHE_DURATION
        ]
        for key in expired_keys:
            del self.response_cache[key]
            print(f"🧹 Cleaned cache: {key}")

# Global instance
huggingface_service = HuggingFaceService()
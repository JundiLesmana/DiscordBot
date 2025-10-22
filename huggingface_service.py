import os
import time
import asyncio
import torch
from transformers import pipeline
import logging

class HuggingFaceService:
    def __init__(self):
        # ⭐ GUNAKAN INI UNTUK RAILWAY - TERBAIK!
        self.model_name = "microsoft/DialoGPT-medium"
        self.pipeline = None
        self.response_cache = {}
        self.CACHE_DURATION = 300
        self._initialize_model()

    def _initialize_model(self):
        """Initialize model dengan optimasi MAXIMAL untuk Railway"""
        try:
            logging.info("🚀 Loading model optimized for Railway...")
            
            # OPTIMASI MAXIMAL UNTUK RAILWAY
            self.pipeline = pipeline(
                "text-generation",
                model=self.model_name,
                torch_dtype=torch.float32,  
                device=-1,  
                model_kwargs={
                    "low_cpu_mem_usage": True,
                    "offload_folder": "./offload",
                    "trust_remote_code": True
                }
            )
            
            logging.info(f"✅ {self.model_name} sukses di-load di Railway!")
            
        except Exception as e:
            logging.error(f"❌ Gagal load model utama: {e}")
            self._load_fallback_model()

    def _load_fallback_model(self):
        """Fallback sequence - dari yang terbaik ke paling ringan"""
        fallback_models = [
            "microsoft/DialoGPT-small",    
            "gpt2",                         
            "distilgpt2"                    
        ]
        
        for model in fallback_models:
            try:
                logging.info(f"🔄 Coba fallback ke: {model}")
                self.model_name = model
                self.pipeline = pipeline(
                    "text-generation",
                    model=model,
                    device=-1  # CPU only
                )
                logging.info(f"✅ Fallback sukses: {model}")
                return
            except Exception as e:
                logging.error(f"❌ Fallback {model} gagal: {e}")
                continue
        
        logging.error("🚨 SEMUA MODEL GAGAL DILOAD!")
        self.pipeline = None

    def _get_smart_prompt(self) -> str:
        # ... (sama seperti sebelumnya)
        return """Your smart prompt here..."""

    async def get_response(self, user_prompt: str, user_id: int) -> str | None:
        try:
            # Cache logic
            cache_key = f"{user_id}_{user_prompt[:50]}"
            if cache_key in self.response_cache:
                cached_data = self.response_cache[cache_key]
                if time.time() - cached_data['timestamp'] < self.CACHE_DURATION:
                    return cached_data['response']
            
            if not self.pipeline:
                return "🤖 AI sedang dalam maintenance, coba lagi nanti."
            
            # Enhanced prompt untuk response yang lebih baik
            enhanced_prompt = self._enhance_prompt(user_prompt)
            full_prompt = f"{self._get_smart_prompt()}\n\nUser: {enhanced_prompt}\nAssistant:"
            
            # Generate dengan timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(self._generate_response, full_prompt),
                timeout=30.0  # Timeout 30 detik
            )
            
            if response:
                self.response_cache[cache_key] = {
                    'response': response,
                    'timestamp': time.time()
                }
                return response
                
        except asyncio.TimeoutError:
            logging.error("⏰ AI response timeout")
            return "⏰ Request timeout, coba lagi dengan pertanyaan lebih singkat."
        except Exception as e:
            logging.error(f"❌ AI error: {e}")
            return None
        
        return None

    def _generate_response(self, prompt: str) -> str:
        """Generate response dengan error handling"""
        try:
            response = self.pipeline(
                prompt,
                max_new_tokens=500,  # Conservative untuk Railway
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                pad_token_id=self.pipeline.tokenizer.eos_token_id,
                repetition_penalty=1.1
            )
            
            generated_text = response[0]['generated_text']
            
            # Extract hanya bagian assistant
            if "Assistant:" in generated_text:
                return generated_text.split("Assistant:")[-1].strip()
            else:
                return generated_text.replace(prompt, "").strip()
                
        except Exception as e:
            logging.error(f"❌ Generation error: {e}")
            return ""

    def _enhance_prompt(self, user_prompt: str) -> str:
        """Tingkatkan prompt pendek"""
        words_count = len(user_prompt.split())
        if words_count <= 3:
            return f"{user_prompt}\n\nTolong berikan penjelasan yang detail dan mudah dipahami."
        return user_prompt

    def clean_old_cache(self):
        current_time = time.time()
        expired_keys = [
            key for key, data in self.response_cache.items()
            if current_time - data['timestamp'] > self.CACHE_DURATION
        ]
        for key in expired_keys:
            del self.response_cache[key]

huggingface_service = HuggingFaceService()
import os, time, asyncio, logging, requests, google.generativeai as genai

class SmartAIService:
    def __init__(self):
        self.ocr_api = os.getenv("OCR_API_KEY")
        self.wolfram_id = os.getenv("WOLFRAM_APP_ID")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.hf_token = os.getenv("HF_TOKEN")
        self.response_cache = {}
        self.CACHE_DURATION = 300

        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)

    async def get_response(self, user_prompt: str, user_id: int):
        """Router pintar: pilih AI sesuai konteks"""
        key = f"{user_id}_{user_prompt[:50]}"
        if key in self.response_cache and time.time() - self.response_cache[key]['t'] < self.CACHE_DURATION:
            return self.response_cache[key]['r']

        if any(k in user_prompt.lower() for k in ["integral", "matrix", "logika", "fungsi", "persamaan", "sin", "cos", "limit"]):
            result = self._wolfram_query(user_prompt)
        elif any(k in user_prompt.lower() for k in ["code", "python", "javascript", "error", "bug", "function", "script", "compile"]):
            result = self._codegemma_query(user_prompt)
        else:
            result = self._gemini_query(user_prompt)

        self.response_cache[key] = {'r': result, 't': time.time()}
        return result

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
            url = "https://api-inference.huggingface.co/models/google/codegemma-7b"
            headers = {"Authorization": f"Bearer {self.hf_token}"}
            payload = {"inputs": prompt, "parameters": {"max_new_tokens": 512}}
            r = requests.post(url, headers=headers, json=payload)
            return r.json()[0]["generated_text"]
        except Exception as e:
            return f"❌ CodeGemma Error: {e}"

    def _gemini_query(self, text):
        try:
            model = genai.GenerativeModel("gemini-pro")
            resp = model.generate_content(text)
            return resp.text
        except Exception as e:
            return f"❌ Gemini Error: {e}"

ai_bot_service = SmartAIService()
"""Day 0 smoke test: checks Gemini, Groq and Langfuse keys from .env."""
import os

import httpx
from dotenv import load_dotenv
from langfuse import get_client
from litellm import completion

load_dotenv()

# 1. Gemini via LiteLLM (also proves the prepay billing works)
r = completion(
    model="gemini/gemini-3.1-flash-lite",
    messages=[{"role": "user", "content": "Say hi in 3 words."}],
)
print("Gemini  ✅", r.choices[0].message.content.strip())

# 2. Groq: is Whisper available to this key?
models = httpx.get(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
).json()
whisper = [m["id"] for m in models["data"] if "whisper" in m["id"]]
print("Groq    ✅" if whisper else "Groq    ❌", whisper)

# 3. Langfuse: are the keys valid?
print("Langfuse ✅" if get_client().auth_check() else "Langfuse ❌")
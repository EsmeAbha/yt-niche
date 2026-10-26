"""One function, three backends: a local Ollama model, the Gemini API, or none.

- ollama: free, runs on your GPU. A 12-14B model (qwen3:14b, gemma3:12b) fits a 16 GB card.
  Note: Ollama and ComfyUI share VRAM; the pipeline unloads the LLM before rendering.
- gemini: Gemini API key from aistudio.google.com (billed separately from Google AI Pro;
  has a free tier with rate limits).
- none: skip the LLM; use Claude Code skills (/niche-ideas) to write ideas from analysis.json.
"""
from __future__ import annotations

import json
import re

import requests


class LLMError(RuntimeError):
    pass


def chat_json(cfg: dict, system: str, user: str, temperature: float = 0.8) -> dict | list:
    lc = cfg.get("llm", {})
    provider = lc.get("provider", "ollama")
    if provider == "ollama":
        text = _ollama(lc, system, user, temperature)
    elif provider == "gemini":
        text = _gemini(lc, system, user, temperature)
    else:
        raise LLMError("llm.provider is 'none'. Use the /niche-ideas Claude skill, or set a provider.")
    return parse_json(text)


def _ollama(lc, system, user, temperature):
    url = lc.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {
        "model": lc.get("ollama_model", "qwen3:14b"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": "json",
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_ctx": lc.get("num_ctx", 16384)},
    }
    try:
        r = requests.post(url, json=body, timeout=lc.get("timeout_s", 900))
    except requests.ConnectionError as e:
        raise LLMError(f"Can't reach Ollama at {url}. Is `ollama serve` running?") from e
    if r.status_code == 400 and "think" in r.text:  # older Ollama / non-thinking model
        body.pop("think")
        r = requests.post(url, json=body, timeout=lc.get("timeout_s", 900))
    r.raise_for_status()
    return r.json()["message"]["content"]


def unload_ollama(cfg: dict) -> None:
    """Free VRAM before ComfyUI renders."""
    lc = cfg.get("llm", {})
    if lc.get("provider") != "ollama":
        return
    try:
        requests.post(lc.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/generate",
                      json={"model": lc.get("ollama_model", "qwen3:14b"), "keep_alive": 0}, timeout=30)
    except requests.RequestException:
        pass


def _gemini(lc, system, user, temperature):
    key = lc.get("gemini_api_key")
    if not key or key.startswith("YOUR_"):
        raise LLMError("Set llm.gemini_api_key (or GEMINI_API_KEY).")
    model = lc.get("gemini_model", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    r = requests.post(url, params={"key": key}, json=body, timeout=300)
    if r.status_code == 404:
        raise LLMError(f"Gemini model '{model}' not found. Update llm.gemini_model in config.yaml.")
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def parse_json(text: str):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise LLMError("Model did not return valid JSON:\n" + text[:500])

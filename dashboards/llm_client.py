"""
Ollama LLM Client for Bugsy / Bug Bot.

Provides clean HTTP integration with local Ollama service with JSON format enforcement,
configurable model selection via environment variables, and fallback support.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama server is unreachable or offline."""
    pass


class OllamaModelError(RuntimeError):
    """Raised when the configured model is unavailable or generation fails."""
    pass


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


PREFERRED_MODELS = [
    "qwen2.5:3b",
    "qwen3:4b",
    "llama3.2:3b",
    "qwen2.5:1.5b",
    "llama3.2:1b",
    "qwen2.5:0.5b",
    "qwen2.5:7b-instruct",
    "qwen2.5:7b",
    "llama3.1:8b",
]


def get_available_models() -> list[str]:
    """Query Ollama /api/tags to list available local models."""
    base_url = get_ollama_base_url()
    req = urllib.request.Request(f"{base_url}/api/tags", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", []) if "name" in m]
            return models
    except Exception as err:
        raise OllamaUnavailableError(f"Cannot reach Ollama at {base_url}: {err}")


def resolve_active_model() -> str:
    """
    Resolve active model to use.
    Prefers BUGSY_LLM_MODEL environment variable if set.
    Otherwise picks the first available lightweight model in PREFERRED_MODELS order.
    """
    explicit = os.getenv("BUGSY_LLM_MODEL")
    try:
        available = get_available_models()
    except OllamaUnavailableError:
        return explicit or "qwen2.5:7b-instruct"

    if not available:
        return explicit or "qwen2.5:7b-instruct"

    if explicit:
        for m in available:
            if m == explicit or m.startswith(explicit.split(":")[0]):
                return m
        return explicit

    # Match preferred small models in priority order
    for pref in PREFERRED_MODELS:
        for m in available:
            if m == pref or m.startswith(pref.split(":")[0]):
                return m

    return available[0]


def check_ollama_status() -> Tuple[bool, str]:
    """
    Check if Ollama server is running and return (is_ready, active_model_name_or_error).
    """
    try:
        active_model = resolve_active_model()
        return True, active_model
    except OllamaUnavailableError as err:
        return False, str(err)


def call_llm_json(
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 600,
) -> Dict[str, Any]:
    """
    Send prompt to Ollama with JSON output formatting (`format: "json"`).

    Returns parsed JSON dictionary.
    """
    base_url = get_ollama_base_url()
    active_model = resolve_active_model()

    payload = {
        "model": active_model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1024,   # reduced for faster responses
            "num_ctx": 4096,
            "top_k": 20,
            "top_p": 0.8,
        }
    }

    if system_prompt:
        payload["system"] = system_prompt

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        print(f"\n[LLM Client] Sending request to Ollama ({active_model})...")
        print(f"[LLM Client] Prompt: {prompt[:300]}...")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            raw_response_text = res_body.get("response", "").strip()
            print(f"[LLM Client] Received response ({len(raw_response_text)} chars).")

            if not raw_response_text:
                raise OllamaModelError(f"Ollama model '{active_model}' returned empty response.")

            # Parse JSON output from model
            try:
                parsed_json = json.loads(raw_response_text)
                return parsed_json
            except json.JSONDecodeError:
                # Safe JSON extraction if wrapped in code block ```json ... ```
                clean_text = raw_response_text
                if "```" in clean_text:
                    parts = clean_text.split("```")
                    for p in parts:
                        cleaned = p.replace("json", "").strip()
                        if cleaned.startswith("{") and "}" in cleaned:
                            end_idx = cleaned.rfind("}")
                            sub_json = cleaned[:end_idx + 1]
                            try:
                                return json.loads(sub_json)
                            except json.JSONDecodeError:
                                pass

                # Fallback: extract from first { to last }
                if "{" in clean_text and "}" in clean_text:
                    start_idx = clean_text.find("{")
                    end_idx = clean_text.rfind("}")
                    sub_str = clean_text[start_idx:end_idx + 1]
                    try:
                        return json.loads(sub_str)
                    except json.JSONDecodeError:
                        pass

                raise OllamaModelError(f"Model response could not be parsed as JSON: {raw_response_text[:300]}")

    except urllib.error.URLError as err:
        if isinstance(err.reason, TimeoutError):
            raise OllamaModelError(f"Ollama generation timed out after {timeout} seconds.")
        raise OllamaUnavailableError(f"Ollama server is unavailable at {base_url}. Details: {str(err)}")
    except Exception as err:
        if isinstance(err, (OllamaUnavailableError, OllamaModelError)):
            raise err
        raise OllamaModelError(f"Error calling Ollama API: {str(err)}")

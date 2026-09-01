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


def get_configured_model() -> str:
    return os.getenv("BUGSY_LLM_MODEL", "qwen2.5:7b-instruct")


def get_available_models() -> list[str]:
    """Fetch list of models currently downloaded in Ollama."""
    url = f"{get_ollama_base_url()}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", [])]
    except (urllib.error.URLError, TimeoutError, Exception) as err:
        raise OllamaUnavailableError(f"Ollama server is unavailable at {get_ollama_base_url()}. Details: {str(err)}")


def resolve_active_model() -> str:
    """
    Resolve active model to use.
    Prefers BUSGY_LLM_MODEL environment variable.
    If exact model is absent, falls back to an available model (e.g. llama3.1:8b).
    """
    configured = get_configured_model()
    try:
        available = get_available_models()
    except OllamaUnavailableError:
        return configured  # Return configured if server status check fails, call will raise OllamaUnavailableError later

    if not available:
        return configured

    # Match exact name or name without tag
    for model_name in available:
        if model_name == configured or model_name.startswith(configured.split(":")[0]):
            return model_name

    # Return first available model if configured one is not yet ready
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

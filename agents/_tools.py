"""
Agent Tools — private module (starts with _), not mapped as a route.

All tool definitions live here. Each tool's function body is the only
thing you need to change when swapping mock data for a real implementation
(e.g. calling a weather API, a translation service, etc.).
"""

import json
import re
from typing import Annotated

from agents import function_tool


# ========== Tool: Get Weather ==========
@function_tool
def get_weather(city: Annotated[str, "The city to get weather for"]) -> str:
    """Get the current weather for a specified city."""
    # TODO: Replace with real weather API (e.g. OpenWeatherMap, wttr.in)
    # Example:
    #   import httpx
    #   resp = httpx.get(f"https://api.openweathermap.org/...?q={city}&appid=YOUR_KEY")
    #   return resp.text
    mock_weather = {
        "city": city,
        "condition": "Sunny",
        "temperature": {"min": 18, "max": 25, "unit": "°C"},
        "wind": "Light breeze",
    }
    return json.dumps(mock_weather, ensure_ascii=False)


# ========== Tool: Get Clothing Advice ==========
@function_tool
def get_clothing_advice(weather: Annotated[str, "The weather description (JSON or plain text)"]) -> str:
    """Give clothing advice based on weather conditions."""
    # TODO: Replace with more sophisticated logic or an external service
    # Basic temperature-aware advice based on input
    if re.search(r"(3[0-9]|4[0-9])\s*°", weather):
        return "It's hot outside — wear a T-shirt and shorts, and remember sunscreen and water."
    if re.search(r"(-\d|[0-9])(?=\s*°)", weather):
        return "It's cold — wear a down jacket or heavy coat, plus a scarf and gloves."
    return "A light long-sleeve jacket with casual pants and sneakers is a comfortable choice for going out."


# ========== Tool: Translate Text ==========
@function_tool
def translate_text(
    text: Annotated[str, "The text to translate"],
    target_language: Annotated[str, "Target language code, e.g. en, ja, fr, ko, de"],
) -> str:
    """Translate text to the specified language."""
    # TODO: Replace with real translation API (e.g. DeepL, Google Translate)
    # Example:
    #   import httpx
    #   resp = httpx.post("https://api.deepl.com/v2/translate", data={...})
    #   return resp.json()["translations"][0]["text"]
    language_names = {
        "en": "English",
        "ja": "日本語",
        "fr": "Français",
        "ko": "한국어",
        "de": "Deutsch",
        "es": "Español",
        "ru": "Русский",
    }
    lang_name = language_names.get(target_language, target_language)
    return f"[Mock translation to {lang_name}]: {text}"


# ========== Tool: Text Statistics ==========
@function_tool
def text_statistics(text: Annotated[str, "The text to analyze"]) -> str:
    """Analyze text and return statistics like character count and word count."""
    char_count = len(text)
    word_count = len(text.split())
    line_count = len(text.split("\n"))
    return json.dumps({"charCount": char_count, "wordCount": word_count, "lineCount": line_count})

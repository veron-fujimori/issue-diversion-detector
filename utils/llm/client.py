import json
import re
from dataclasses import dataclass
from openai import APIError, OpenAI, RateLimitError
from config.settings import settings
from utils.logger import logger

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?(.*?)```", re.DOTALL)
_JSON_OBJECT_PATTERN = re.compile(r"\{[^}]*\}")


def _extract_json(text: str) -> dict:
    """
    web_search-grounded responses kadang gak murni JSON — bisa ada code fence,
    kutipan sumber, atau teks tambahan di sekitar objek JSON-nya walau prompt
    sudah minta "HANYA JSON". json.loads(text) langsung gampang gagal kalau
    formatnya sedikit meleset. Coba parse langsung dulu, baru fallback ke
    strip code fence / ekstrak blok {...} pertama.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = _JSON_FENCE_PATTERN.search(text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    object_match = _JSON_OBJECT_PATTERN.search(text)
    if object_match:
        return json.loads(object_match.group(0))

    raise json.JSONDecodeError("no JSON object found in text", text, 0)


@dataclass
class LLMResponse:
    content: str | dict
    model: str

@dataclass
class SearchLLMResponse:
    content: str | dict
    model: str
    grounded: bool

class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL

    def chat(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMResponse:
        content = None
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"} if json_mode else None,
            )
            content = response.choices[0].message.content
            if json_mode:
                content = json.loads(content)
            logger.debug(f"LLM | model={self.model} | json_mode={json_mode}")
            return LLMResponse(content=content, model=response.model)

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e} | content: {content}")
            raise
        except RateLimitError:
            logger.error("Rate limit hit")
            raise
        except APIError as e:
            logger.error(f"API error: {e}")
            raise

    def chat_with_search(self, prompt: str, system: str) -> SearchLLMResponse:
        text = None
        try:
            response = self._client.responses.create(
                model=settings.OPENAI_SEARCH_MODEL,
                max_output_tokens=8192,
                tools=[{"type": "web_search"}],
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )

            text = response.output_text
            content = _extract_json(text)

            grounded = any(
                getattr(item, "type", None) == "web_search_call"
                for item in response.output
            )

            if not grounded:
                logger.warning(
                    "LLM | chat_with_search | model did not perform a web_search_call — "
                    "response is likely from parametric memory, not grounded"
                )

            logger.debug(
                f"LLM | chat_with_search | model={settings.OPENAI_SEARCH_MODEL} | grounded={grounded}"
            )
            return SearchLLMResponse(
                content=content,
                model=settings.OPENAI_SEARCH_MODEL,
                grounded=grounded,
            )

        except json.JSONDecodeError as e:
            logger.error(f"context_checker | JSON parse error: {e} | raw: {text}")
            raise
        except RateLimitError:
            logger.error("Rate limit hit (web_search)")
            raise
        except APIError as e:
            logger.error(f"API error (web_search): {e}")
            raise


llm = LLMClient()
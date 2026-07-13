import json
from dataclasses import dataclass
from typing import Union
from openai import OpenAI, APIError, RateLimitError
from config.settings import settings
from utils.logger import logger


@dataclass
class LLMResponse:
    content: Union[str, dict]
    model: str


@dataclass
class SearchLLMResponse:
    content: Union[str, dict]
    model: str
    grounded: bool   # True kalau web_search_call beneran terjadi di response


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
        """
        Dipakai khusus context_checker — butuh grounding via web search asli,
        bukan tebakan dari memori parametrik model.
        """
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
            content = json.loads(text)

            # Verifikasi web search BENERAN terjadi, bukan model jawab dari memori
            grounded = any(
                getattr(item, "type", None) == "web_search_call"
                for item in response.output
            )

            if not grounded:
                logger.warning(
                    "LLM | chat_with_search | model tidak melakukan web_search_call — "
                    "jawaban kemungkinan dari memori parametrik, bukan hasil grounding"
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
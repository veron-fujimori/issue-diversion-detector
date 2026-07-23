import json
from dataclasses import dataclass
from openai import APIError, OpenAI, RateLimitError
from config.settings import settings
from utils.logger import logger

@dataclass
class LLMResponse:
    content: str | dict
    model: str

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

llm = LLMClient()
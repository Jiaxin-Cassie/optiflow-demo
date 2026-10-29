"""One audited, bounded API path for every role."""
from time import perf_counter
from src.config import Config
from src.errors import LLMCallError
from src.utils import estimate_tokens, remove_think_blocks


class LLMClient:
    def __init__(self, config: Config):
        if not config.api_key:
            raise ValueError("API key is missing. Configure src/config.py or its environment input.")
        from openai import OpenAI
        self.config = config
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                             max_retries=0, timeout=getattr(config, "llm_timeout", 180))
        self.llm_calls = 0
        self.token_estimate = 0
        self.interactions = []

    def _journal(self, record):
        directory = getattr(self.config, 'llm_journal_dir', None)
        if directory:
            from pathlib import Path
            from uuid import uuid4
            from src.storage import atomic_json
            identifier = record.setdefault('journal_id', uuid4().hex)
            atomic_json(Path(directory) / f"call_{record['call_index']:04d}_{identifier}.json", record)

    def chat(self, messages, temperature=None, agent_name="unknown_agent", max_tokens=None):
        limits = getattr(self.config, "stage_max_tokens", {})
        limit = max_tokens if max_tokens is not None else limits.get(agent_name, 2048)
        reasoning = agent_name in getattr(self.config, "reasoning_agents", ())
        prompt_estimate = sum(estimate_tokens(m.get("content", "")) for m in messages)
        request = dict(model=self.config.model, messages=messages, stream=False,
                       temperature=self.config.temperature if temperature is None else temperature,
                       max_tokens=int(limit),
                       extra_body={"thinking": {"type": "enabled" if reasoning else "disabled"}})
        if reasoning:
            request.update(reasoning_effort=getattr(self.config, "reasoning_effort", "medium"))
        attempts = getattr(self.config, "llm_attempts", 2)
        for attempt in range(attempts):
            started = perf_counter()
            self.llm_calls += 1
            record = {"call_index": self.llm_calls, "agent_name": agent_name,
                      "model": self.config.model, "temperature": request["temperature"],
                      "reasoning_enabled": reasoning, "reasoning_effort": request.get("reasoning_effort"),
                      "thinking_type": request["extra_body"]["thinking"]["type"],
                      "max_tokens": limit, "messages": messages, "attempt": attempt + 1,
                      "prompt_tokens_estimate": prompt_estimate, "response_tokens_estimate": 0,
                      "usage": None, "response": "", "reasoning_response": ""}
            from datetime import datetime, timezone
            record.update(started_at_utc=datetime.now(timezone.utc).isoformat(),
                          outcome='in_flight', usage_unknown=True, latency_seconds=0.0)
            self._journal(record)
            try:
                response = self.client.chat.completions.create(**request)
            except Exception as exc:
                kind = type(exc).__name__
                status = getattr(exc, 'status_code', None)
                if status == 402:
                    kind = 'QuotaExceededError'
                record['http_status'] = status
                record.update(outcome="api_error", error_type=kind,
                              latency_seconds=perf_counter() - started, usage_unknown=True)
                self.interactions.append(record)
                self._journal(record)
                if kind in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"} and attempt + 1 < attempts:
                    continue
                raise LLMCallError(agent_name, kind) from None
            choice = response.choices[0]
            content = remove_think_blocks(choice.message.content or "")
            reasoning_text = getattr(choice.message, "reasoning_content", None) or ""
            usage = getattr(response, "usage", None)
            if usage:
                details = getattr(usage, "completion_tokens_details", None)
                record["usage"] = {"prompt_tokens": getattr(usage, "prompt_tokens", None),
                                   "completion_tokens": getattr(usage, "completion_tokens", None),
                                   "total_tokens": getattr(usage, "total_tokens", None),
                                   "reasoning_tokens": getattr(details, "reasoning_tokens", None)}
            record.update(response=content, reasoning_response=reasoning_text,
                          response_tokens_estimate=estimate_tokens(content + reasoning_text),
                          latency_seconds=perf_counter() - started,
                          finish_reason=choice.finish_reason, outcome="ok")
            record.update(provider_model=getattr(response, 'model', None), response_id=getattr(response, 'id', None))
            reported = (record["usage"] or {}).get("total_tokens")
            record["usage_unknown"] = reported is None
            record["token_accounting_source"] = "provider" if reported is not None else "estimate"
            record["accounted_tokens"] = reported if reported is not None else prompt_estimate + record["response_tokens_estimate"]
            self.token_estimate += record["accounted_tokens"]
            self.interactions.append(record)
            if choice.finish_reason == "length":
                record["outcome"] = "output_truncated"
                self._journal(record)
                raise LLMCallError(agent_name, "output_truncated")
            if not content.strip():
                record["outcome"] = "empty_response"
                self._journal(record)
                raise LLMCallError(agent_name, "empty_response")
            self._journal(record)
            return content

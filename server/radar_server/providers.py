"""No external credentials or API calls. The extractive provider is a baseline."""
import json
import math
from typing import Protocol

from .analysis_models import AnalysisInput, ChargeLimit, ProviderResult, Usage
from .topics import excluded, is_correction, normalize, tokens


class ProviderFailure(Exception):
    def __init__(self, code="provider_unavailable", permanent=False):
        super().__init__(code)
        self.code = code
        self.permanent = permanent


class SummaryProvider(Protocol):
    external: bool
    def maximum_charge(self, batch: AnalysisInput) -> ChargeLimit: ...
    def generate(self, batch: AnalysisInput) -> ProviderResult: ...


def estimated_tokens(text):
    return math.ceil(len(text.encode("utf-8")) / 4)


class ExtractiveProvider:
    """Keyword relevance and quoted source excerpts, with simulated token counts."""
    external = False

    @staticmethod
    def render(batch):
        summaries = []
        for topic in batch.topics:
            text = normalize("\n".join(m.text for m in topic.messages))
            hits = [term for term in batch.profile.interests if normalize(term) in text]
            positive = any(len(tokens(example) & tokens(text)) >= 2 for example in batch.profile.positive_examples)
            negative = any(len(tokens(example) & tokens(text)) >= 2 for example in batch.profile.negative_examples)
            score = min(100, 80 + 5 * len(hits)) if hits or positive else 20
            if excluded(topic, batch.profile.exclude_topics) or negative:
                score = 0
            selected = list(topic.messages[:2])
            # Do not omit the latest correction when a URL thread contains many updates.
            corrections = [m for m in topic.messages if is_correction(m.text)]
            last = corrections[-1] if corrections else topic.messages[-1]
            if last not in selected:
                selected.append(last)
            uncertain = any(m.quality != "structured" or m.source_time is None for m in topic.messages)
            summaries.append({
                "topic_id": topic.topic_id,
                "title": topic.messages[0].text[:60],
                "points": [{"text": m.text[:180], "evidence_ids": [m.event_id]} for m in selected],
                "relevance": score, "importance": 50 if hits else 20,
                "uncertainty": "conflicting_messages" if corrections else "limited_context" if uncertain else "none",
                "source_urls": list(dict.fromkeys(u for m in selected for u in m.urls))[:50],
            })
        return {"topics": summaries}

    def maximum_charge(self, batch):
        serialized = batch.serialized()
        if len(serialized) > batch.profile.max_input_chars:
            raise ProviderFailure("input_too_large", permanent=True)
        return ChargeLimit(tokens=estimated_tokens(serialized) + batch.profile.max_output_tokens, cost_microusd=0)

    def generate(self, batch):
        self.maximum_charge(batch)
        output = self.render(batch)
        output_tokens = estimated_tokens(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
        if output_tokens > batch.profile.max_output_tokens:
            raise ProviderFailure("output_limit", permanent=True)
        return ProviderResult(output, Usage(
            input_tokens=estimated_tokens(batch.serialized()), output_tokens=output_tokens,
            cost_microusd=0, measured=False,
        ), "extractive-v1")

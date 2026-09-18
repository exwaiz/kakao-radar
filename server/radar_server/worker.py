"""Explicitly enabled M3 worker; the default launches no provider."""
import argparse
import os
import re
import time
from uuid import UUID

from pydantic import ValidationError

from .analysis_models import AnalysisInput, ChargeLimit, Usage, validate_output
from .analysis_store import AnalysisStore
from .providers import ExtractiveProvider, ProviderFailure, SummaryProvider
from .store import Store
from .topics import prepare_topics


class Worker:
    def __init__(self, analysis: AnalysisStore, provider: SummaryProvider):
        self.analysis = analysis
        self.provider = provider

    def process(self, device, room, force=False):
        claim = self.analysis.claim(device, room, force=force)
        if not claim:
            return "idle"
        messages = self.analysis.messages(claim)
        if messages is None:
            self.analysis.fail(claim, "source_expired", permanent=True)
            return "failed"
        targets = self.analysis.targets(claim)
        reactions = any(any(word in term for word in ('공감','반응','웃','reaction')) for term in claim.profile.interests)
        topics = tuple(t for t in prepare_topics(messages,preserve_reactions=reactions) if any(m.event_id in targets for m in t.messages))
        batch = AnalysisInput(topics, claim.profile, claim.profile_version)
        # A chatter-only batch needs no provider call or budget reservation.
        if not batch.topics:
            output = validate_output({"topics": []}, batch)
            return "completed" if self.analysis.complete(claim, batch, output, "preprocessing-v1") else "superseded"
        try:
            if not isinstance(self.provider.external, bool):
                raise ValueError("Invalid provider contract")
            limit = ChargeLimit.model_validate(self.provider.maximum_charge(batch))
            if self.provider.external and limit.cost_microusd == 0:
                raise ValueError("External provider needs a priced maximum charge")
        except ProviderFailure as error:
            self.analysis.fail(claim, error.code, permanent=True)
            return "failed"
        except Exception:
            self.analysis.fail(claim, "invalid_usage", permanent=True)
            return "failed"
        call_id = self.analysis.reserve(claim, limit)
        if call_id is None:
            return "deferred"
        try:
            result = self.provider.generate(batch)
        except ProviderFailure as error:
            # Failure may happen after remote billing. Keep the full reservation.
            self.analysis.fail(claim, error.code, permanent=error.permanent)
            return "failed"
        except Exception:
            self.analysis.fail(claim, "provider_unavailable")
            return "failed"
        try:
            usage = Usage.model_validate(result.usage)
        except (ValidationError, ValueError, AttributeError):
            self.analysis.fail(claim, "invalid_usage")
            return "failed"
        if not self.analysis.settle(call_id, usage):
            self.analysis.fail(claim, "budget_overrun", permanent=True)
            return "failed"
        try:
            if not isinstance(result.model, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", result.model):
                raise ValueError("Invalid model metadata")
            output = validate_output(result.output, batch)
        except (ValidationError, ValueError, TypeError, AttributeError) as error:
            reasons = {'Invalid topic set':'topic_set', 'Invalid evidence scope':'evidence_scope',
                       'Invalid source URLs':'source_urls', 'Uncertain source requires a caveat':'source_caveat'}
            reason = reasons.get(str(error), 'schema') if isinstance(error, ValueError) and not isinstance(error, ValidationError) else 'schema'
            print('analysis_output_rejected:' + reason, flush=True)
            if isinstance(error, ValidationError):
                # Field names and error types only; never values or validation messages.
                print('analysis_schema_errors:' + ','.join('.'.join(str(part) for part in item['loc']) + ':' + item['type'] for item in error.errors(include_input=False,include_url=False)[:5]), flush=True)
            self.analysis.fail(claim, "invalid_output")
            return "failed"
        return "completed" if self.analysis.complete(claim, batch, output, result.model) else "superseded"

    def run_once(self, force=False, device=None, room=None):
        outcomes = {}
        for target in self.analysis.rooms():
            if device and target["device_id"] != device or room and target["room_id"] != room:
                continue
            outcome = self.process(target["device_id"], target["room_id"], force)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return outcomes


def main():
    parser = argparse.ArgumentParser(description="M3 analysis worker")
    parser.add_argument("--provider", choices=["disabled", "extractive", "openai"], default=os.environ.get("RADAR_ANALYSIS_PROVIDER", "disabled"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true", help="Bypass count/time scheduling only")
    parser.add_argument("--device", type=UUID)
    parser.add_argument("--room", type=UUID)
    args = parser.parse_args()
    if args.provider not in ("disabled", "extractive", "openai"):
        parser.error("Unsupported analysis provider")
    if args.provider == "disabled":
        print("Analysis provider is disabled")
        return
    if args.force and not args.once:
        parser.error("--force requires --once")
    store = Store(os.environ["RADAR_DATABASE_URL"])
    store.migrate()
    if args.provider == "openai":
        from .openai_provider import OpenAIProvider
        try:
            provider = OpenAIProvider()
        except ProviderFailure:
            parser.exit(1, "OpenAI credential configuration is incomplete\n")
    else:
        provider = ExtractiveProvider()
    worker = Worker(AnalysisStore(store), provider)
    while True:
        try:
            print(worker.run_once(args.force, args.device, args.room), flush=True)
        except Exception:
            # Exceptions from DB/provider libraries can contain row or request content.
            print("Worker storage temporarily unavailable", flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(15)


if __name__ == "__main__":
    main()

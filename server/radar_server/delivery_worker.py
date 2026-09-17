"""Opt-in M4 worker. Default startup performs no delivery and no network calls."""
import argparse
import os
import time

import psycopg

from .delivery_channels import ChannelConfigurationError, NtfyChannel
from .delivery_store import DeliveryStore
from .store import Store


class DeliveryWorker:
    def __init__(self, delivery, channel):
        self.delivery, self.channel = delivery, channel

    def process(self, device):
        # Recover a stale send before planning, otherwise its active row blocks planning.
        self.delivery.status(device)
        self.delivery.plan(device)
        claim = self.delivery.begin_send(device)
        if claim is None:
            return "idle"
        try:
            result = self.channel.publish(claim)
        except Exception:
            # Unknown exceptions after starting may follow a successful remote commit.
            self.delivery.finish(claim, "uncertain", "channel_unavailable")
            return "uncertain"
        saved = self.delivery.finish(claim, result.outcome, result.code, result.message_id, result.retry_after)
        return result.outcome if saved else "stale"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["disabled", "ntfy"], default=os.environ.get("RADAR_DELIVERY_PROVIDER", "disabled"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.provider not in ("disabled", "ntfy"):
        parser.exit(1, "Unknown delivery provider\n")
    if args.provider == "disabled":
        print("Delivery disabled")
        return
    try:
        channel = NtfyChannel.from_env()
    except (ChannelConfigurationError, ValueError):
        parser.exit(1, "Delivery channel configuration is incomplete or invalid\n")
    store = Store(os.environ["RADAR_DATABASE_URL"])
    store.migrate()
    delivery = DeliveryStore(store)
    worker = DeliveryWorker(delivery, channel)
    while True:
        try:
            devices = delivery.devices()
            for device in devices:
                try:
                    print({"device_id": str(device), "result": worker.process(device)}, flush=True)
                except PermissionError:
                    continue
        except psycopg.Error:
            print("Delivery storage temporarily unavailable", flush=True)
        if args.once:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()

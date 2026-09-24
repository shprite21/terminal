import argparse
from datetime import date
import getpass
import json
import os
import sys
import warnings
from pathlib import Path
from .storage import Store, canonical, digest, now


class SetupError(Exception):
    """Safe local setup guidance; never include entered secrets or backend errors."""


def configure_credentials(show_input=False):
    import keyring
    if not sys.stdin.isatty():
        raise SetupError("Run the credentials command on its own in an interactive PowerShell terminal. Do not pipe or redirect credential input.")
    visibility = "Input is visible in this terminal; check each value before pressing Enter." if show_input else "Hidden input shows no characters or asterisks."
    print("Enter each value when prompted. " + visibility + " Ctrl+C cancels.")
    values = {}
    fields = ("API_KEY", "CLIENT_CODE", "PIN")

    def read_secret(field):
        for attempt in range(3):
            # Refuse getpass's echoing fallback when hidden input is unavailable.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    value = (input(field + " (visible): ") if show_input else getpass.getpass(field + " (hidden): ")).strip()
                except getpass.GetPassWarning:
                    raise SetupError("Hidden input is unavailable. Run this command on its own in a normal interactive PowerShell terminal.") from None
            if value:
                return value
            print(field + " was empty. Enter its value.")
        raise SetupError(field + " was empty after three attempts. Nothing was saved. Run the credentials command again when ready.")

    try:
        for field in fields:
            values[field] = read_secret(field)
        if input("Store optional TOTP seed in OS keyring? Type YES, or press Enter to skip: ").strip() == "YES":
            values["TOTP_SEED"] = read_secret("TOTP_SEED")
    except (EOFError, KeyboardInterrupt):
        raise SetupError("Credential setup cancelled before saving. Run the command again in your local terminal when ready.") from None
    # Collect and validate all entries before modifying the OS store.
    try:
        for field, value in values.items():
            keyring.set_password("evidence-angel-one", field, value)
    except Exception:
        raise SetupError("The OS credential store could not save all entries. Setup may be partial; check the Windows credential store and run setup again.") from None
    print("Saved in OS credential store. Credentials were not written to project files. Run the status command next; authentication is verified separately in the app.")


def main():
    parser = argparse.ArgumentParser(description="Evidence real-market-data research")
    parser.add_argument("--store", default=str(Path(os.environ.get('Q_FLAGSHIP_DATA', Path(__file__).resolve().parents[3] / '.data/flagship')) / 'evidence'))
    commands = parser.add_subparsers(dest="command", required=True)
    credentials = commands.add_parser("credentials", help="Store credentials in the OS keyring using local prompts")
    credentials.add_argument("--show-input", action="store_true", help="Show entered credentials in the local terminal so you can verify them before submitting")
    commands.add_parser("status")
    commands.add_parser("master")
    search = commands.add_parser("search")
    search.add_argument("version")
    search.add_argument("query")
    download = commands.add_parser("download")
    download.add_argument("request", help="JSON: instruments, start, end")
    download.add_argument("--refresh", action="store_true", help="Re-fetch all chunks; frozen datasets remain immutable")
    freeze = commands.add_parser("freeze-download")
    freeze.add_argument("download_id")
    freeze.add_argument("calendar")
    freeze.add_argument("--price-note", required=True)
    imp = commands.add_parser("import-csv")
    imp.add_argument("csv")
    imp.add_argument("metadata")
    h = commands.add_parser("hypothesis")
    h.add_argument("json")
    s = commands.add_parser("strategy")
    s.add_argument("json")
    run = commands.add_parser("run")
    run.add_argument("strategy_id")
    run.add_argument("--partition", choices=["training", "validation", "holdout"], default="validation")
    args = parser.parse_args()
    if args.command == "credentials":
        configure_credentials(show_input=args.show_input)
        return
    store = Store(args.store)
    if args.command == "status":
        from .provider import credentials_ready
        print(canonical({"credentials_configured": bool(credentials_ready()), "authenticated_ingestion": "unverified until a successful real download",
                         "datasets": len(store.list("dataset")), "reports": len(store.list("report"))}))
    elif args.command == "master":
        from .provider import fetch_master
        print(fetch_master(store))
    elif args.command == "search":
        from .provider import search_master
        print(canonical([i.model_dump(mode="json") for i in search_master(store, args.version, args.query)]))
    elif args.command == "download":
        from .provider import AngelOneDataProvider, download, validate_mappings
        from .models import Instrument
        request = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
        instruments = [Instrument.model_validate(i) for i in request["instruments"]]
        validate_mappings(store, instruments)
        provider = AngelOneDataProvider(store)
        provider.connect(getpass.getpass("Current TOTP (hidden; blank uses configured seed): ") or None)
        state = download(provider, store, instruments, date.fromisoformat(request["start"]), date.fromisoformat(request["end"]), refresh=args.refresh)
        print(store.put("download", state))
    elif args.command == "freeze-download":
        print(freeze_download(store, args.download_id, json.loads(Path(args.calendar).read_text(encoding="utf-8-sig")), args.price_note))
    elif args.command == "import-csv":
        import pandas as pd
        from .data import freeze_dataset
        raw = Path(args.csv).read_bytes()
        metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8-sig"))
        print(freeze_dataset(store, pd.read_csv(args.csv), metadata["source"], metadata["instruments"], metadata["calendar"],
                             date.fromisoformat(metadata["start"]), date.fromisoformat(metadata["end"]), metadata["price_note"], raw, metadata.get("corporate_actions", [])))
    elif args.command in {"hypothesis", "strategy"}:
        from .experiments import save_hypothesis, freeze_strategy
        config = json.loads(Path(args.json).read_text(encoding="utf-8-sig"))
        print((save_hypothesis if args.command == "hypothesis" else freeze_strategy)(store, config))
    elif args.command == "run":
        from .experiments import run_experiment
        print(run_experiment(store, args.strategy_id, args.partition))


def freeze_download(store, download_id, calendar, price_note, actions=()):
    from .models import Calendar
    from .data import normalize_download, freeze_dataset
    state = store.get(download_id, "download")
    cal = Calendar.model_validate(calendar)
    payload = canonical(state).encode()
    source = {"provider": "Angel One SmartAPI", "url": "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData",
              "retrieved_at": max(c["retrieved_at"] for c in state["chunks"].values()), "description": "Authenticated candle download; chunk requests, instrument mappings and retrieval timestamps recorded",
              "raw_sha256": digest(payload), "real_data_attestation": True}
    return freeze_dataset(store, normalize_download(state, cal), source, state["request"]["instruments"], cal,
                          date.fromisoformat(state["request"]["start"]), date.fromisoformat(state["request"]["end"]), price_note, payload, actions)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        from .provider import ProviderError
        # No tracebacks or raw SDK/server responses on credential paths.
        if isinstance(exc, (ProviderError, SetupError)):
            message = str(exc)
        elif isinstance(exc, ValueError):
            message = "Invalid request or unmet data requirement. Validate input against documented contracts."
        else:
            message = "Operation unavailable; check local setup and required inputs."
        print(message)
        raise SystemExit(1)

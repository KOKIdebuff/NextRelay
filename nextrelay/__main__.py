"""Run with python -m nextrelay; no package installation is necessary."""
import argparse
import logging
import sqlite3
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .app import create_app
from .config import ConfigError, load_settings
from .db import SCHEMA_VERSION, SchemaError, initialize, seed_synthetic


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        # Default WSGI logging includes full URLs; disable it at this boundary.
        pass

    def handle(self):
        self.request.settimeout(5)
        super().handle()


def main():
    parser = argparse.ArgumentParser(description="NextRelay synthetic local development")
    parser.add_argument("command", choices=("init-db", "seed-dev", "serve"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = load_settings()
        if args.command == "init-db":
            initialize(settings.database)
            print(f"Development database initialized/upgraded (schema v{SCHEMA_VERSION}; synthetic only).")
        elif args.command == "seed-dev":
            seed_synthetic(settings.database, settings.subject)
            print("Synthetic access fixtures ready.")
        else:
            application = create_app(settings)
            with make_server(
                settings.host, settings.port, application, handler_class=QuietHandler
            ) as server:
                print(f"NextRelay T04: http://{settings.host}:{settings.port} (synthetic development only)", flush=True)
                server.serve_forever()
    except (ConfigError, SchemaError) as error:
        parser.exit(2, f"{error}\n")
    except (sqlite3.Error, OSError):
        parser.exit(2, "Local storage/server unavailable; check configured path and port.\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

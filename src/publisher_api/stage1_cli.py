from __future__ import annotations

import argparse
import json
import uuid
from typing import Any, NoReturn

from alembic.config import Config
from pydantic import ValidationError

from alembic import command
from publisher_api.settings import Settings
from publisher_api.stage1_database import create_database_engine, create_session_factory
from publisher_api.stage1_domain import DomainError
from publisher_api.stage1_publisher import configured_publisher
from publisher_api.stage1_services import Stage1Services


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 owner operations")
    commands = parser.add_subparsers(dest="command", required=True)

    database = commands.add_parser("database")
    database_commands = database.add_subparsers(dest="database_command", required=True)
    database_commands.add_parser("upgrade")
    database_commands.add_parser("current")

    import_connection = commands.add_parser("import-stage0-connection")
    import_connection.add_argument("--confirm-import", action="store_true")

    reconcile = commands.add_parser("reconcile-stale-publications")
    mode = reconcile.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")

    inspect_publication = commands.add_parser("inspect-publication")
    inspect_publication.add_argument("publication_id", type=uuid.UUID)

    commands.add_parser("export-safe-audit")
    return parser


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError:
        raise SystemExit(
            json.dumps(
                {
                    "code": "CONFIGURATION_INVALID",
                    "message": "Stage 1 configuration is invalid",
                    "retryable": False,
                },
                sort_keys=True,
            )
        ) from None


def _alembic_config() -> Config:
    return Config("alembic.ini")


def _services(settings: Settings) -> tuple[Any, Stage1Services]:
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    return engine, Stage1Services(sessions, settings, configured_publisher(settings))


def _safe_publication(publication: Any, attempts: int) -> dict[str, Any]:
    return {
        "id": str(publication.id),
        "status": publication.status,
        "request_fingerprint": publication.request_fingerprint,
        "post_identifier_present": publication.linkedin_post_identifier is not None,
        "failure_category": publication.failure_category,
        "safe_error_code": publication.safe_error_code,
        "request_attempted": publication.request_attempted,
        "response_received": publication.response_received,
        "attempts": attempts,
    }


def _fail(exc: DomainError) -> NoReturn:
    raise SystemExit(
        json.dumps(
            {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            },
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "database":
        config = _alembic_config()
        if args.database_command == "upgrade":
            command.upgrade(config, "head")
        else:
            command.current(config, verbose=False)
        return 0

    settings = _settings()
    engine, services = _services(settings)
    try:
        if args.command == "import-stage0-connection":
            result = services.connections.import_stage0(confirm=args.confirm_import)
        elif args.command == "reconcile-stale-publications":
            identifiers = services.publications.reconcile_stale(
                threshold_seconds=settings.stale_publication_seconds,
                confirm=args.confirm,
            )
            result = {
                "dry_run": not args.confirm,
                "count": len(identifiers),
                "publication_ids": [str(item) for item in identifiers],
                "network_requests": 0,
            }
        elif args.command == "inspect-publication":
            publication = services.publications.get(args.publication_id)
            result = _safe_publication(
                publication,
                services.publication_attempt_count(publication.id),
            )
        else:
            result = {"events": services.safe_audit_export()}
    except DomainError as exc:
        _fail(exc)
    finally:
        engine.dispose()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

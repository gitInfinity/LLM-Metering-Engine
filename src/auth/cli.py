import argparse

from src.db.database import engine
from src.core.logging import configure_logging, error
from sqlalchemy.exc import OperationalError
from .service import AuthService


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Local administrator API-key management")
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--tenant-id", type=int, required=True)
    issue.add_argument("--days", type=int, default=90)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--key-id", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "issue":
            key_id, token = AuthService.issue_key(args.tenant_id, args.days)
            print(f"Key ID: {key_id}\nAPI key (shown once): {token}")
        else:
            AuthService.revoke_key(args.key_id)
            print("API key revoked.")
    except ValueError as exc:
        parser.error(str(exc))
    except OperationalError:
        error(__name__, "Database unavailable during key management")
        raise SystemExit("Database temporarily unavailable. Check PostgreSQL connectivity.") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

import os

from dotenv import load_dotenv
from supabase import create_client, Client


# ----------------------------------
# LOAD ENV VARIABLES
# ----------------------------------

load_dotenv()


SUPABASE_URL = os.getenv(
    "SUPABASE_URL"
)

SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY"
)


if not SUPABASE_URL:

    raise ValueError(
        "SUPABASE_URL not found in .env"
    )


if not SUPABASE_KEY:

    raise ValueError(
        "SUPABASE_KEY not found in .env"
    )


# ----------------------------------
# CREATE CLIENT
# ----------------------------------

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

# Reconnect-and-retry-once for stale/closed pooled connections (see
# database/retry_transport.py for exactly what is and isn't retried).
from database.retry_transport import install as _install_retry  # noqa: E402

_install_retry(supabase)


# ----------------------------------
# TEST CONNECTION
# ----------------------------------

try:

    supabase.table(
        "users"
    ).select(
        "id"
    ).limit(
        1
    ).execute()

    print(
        "\n========== SUPABASE =========="
    )

    print(
        "Connected Successfully!"
    )

    print(
        "Database: AI_TUTOR2"
    )

    print(
        "==============================\n"
    )

except Exception as e:

    print(
        f"Supabase Connection Error: {e}"
    )
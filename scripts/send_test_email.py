"""Send one test email through Sellbird's configured mailbox.

Usage (from the project folder, with the venv active):
    python scripts/send_test_email.py recipient@example.com

Uses the same provider, sender identity and settings the heartbeat loop uses
(sellbird.local.yaml / sellbird.yaml + .env), so a success here means the real
sending path works. It sends exactly one email and records nothing in the
database. Passwords are never printed.
"""

import asyncio
import sys
from datetime import datetime

from sellbird.config import load_config, load_env
from sellbird.integrations.mail_provider import get_mail_provider


async def main(to_email: str) -> int:
    config, env = load_config(), load_env()
    provider = get_mail_provider(config, env)
    if provider is None or not provider.is_configured():
        print("No mailbox is configured. Check channels.email.provider and the SMTP_* values in .env.")
        return 1
    print(f"Provider: {provider.name}")
    ok, detail = await provider.test_connection()
    print(f"Connection test: {'OK' if ok else 'FAILED'} - {detail}")
    if not ok:
        return 1
    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    result = await provider.send_email(
        to_email,
        f"Chirayu Power Outreach test - {stamp}",
        "Hello,\n\nThis is a test email sent by Chirayu Power Outreach to confirm the "
        "mailbox is connected and sending works.\n\nNo action is needed.\n",
    )
    if result.ok:
        print(f"Sent to {to_email}. Message-ID: {result.message_id}")
        return 0
    print(f"Send FAILED: {result.error}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1].strip())))

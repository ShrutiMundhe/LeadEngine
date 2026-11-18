"""Email setup: everything about how emails go out, editable from the dashboard.

The dashboard's Email setup tab reads and writes these settings so nobody has
to edit YAML by hand:

- sending   channels.email.provider, max_daily_sends
- schedule  usage.quiet_hours (start, end, timezone), heartbeat interval
- footer    compliance.postal_address, opt_out_line, do_not_contact
- signature channels.email.signature (logo image, width, alt text, link)
- template  writer.email_rules and the rules file itself (skills/email_rules.md)

Every save is checked by loading the whole config the way Sellbird will
(SellbirdConfig), so the dashboard can never write a file that stops Sellbird
starting. A .bak of the file as it was is kept, as the Your company tab does.
"""

from __future__ import annotations

import base64
from pathlib import Path

import yaml
from pydantic import ValidationError

from sellbird.config import DEFAULT_OPT_OUT_LINE, MAX_EMAIL_RULES_CHARS, SellbirdConfig
from sellbird.integrations.signature import MAX_LOGO_BYTES, SignatureError, load_signature
from sellbird.textio import read_user_text

PROVIDERS = ("smtp", "microsoft", "gmail", "instantly")
RULES_FILE = "skills/email_rules.md"
LOGO_DIR = "assets/email"
MAX_TEXT = 2000
MAX_ITEMS = 500

COMMON_TIMEZONES = [
    "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "Europe/Berlin",
    "America/New_York", "America/Chicago", "America/Los_Angeles", "Australia/Sydney", "UTC",
]

STARTER_TEMPLATE = """# Email template

These rules replace the built-in email style. Chirayu Power still writes each
email itself, personalised from what it found about the company; this file
decides the shape, tone and content.

## Length and shape
- Email 1: 80 to 120 words. Email 2: under 80 words. Email 3: under 50 words.
- Start with one specific thing about their plant, site or industry.
- One short paragraph on what we do, then the offer, then one clear question.

## What to say about us
- We are an EPC company that designs, builds and maintains solar plants:
  rooftop, ground-mounted and open access, plus solar thermal for process heat.
- Mention the electricity bill saving in rupees or percent when we can estimate it.
- CAPEX (they own it) and RESCO (pay per unit, no upfront cost) are both available.

## Subject lines
- Lowercase, 2 to 5 words, mention their company or plant. No exclamation marks.

## Sign-off
- Sign with the sender's name and role, then "Chirayu Power Pvt. Ltd."

## Never
- No "I hope this email finds you well", no emojis, no ALL CAPS.
- Never invent numbers, customers or projects that are not in our product knowledge.
"""


class SetupError(ValueError):
    """A value the dashboard can't save, with a message for the user."""


# ── Reading ───────────────────────────────────────────────────────────────

def _rules_path(root: Path) -> Path:
    return Path(root) / RULES_FILE


def view(config, root: Path) -> dict:
    """What the Email setup tab shows."""
    email = config.channels.email
    quiet = config.usage.quiet_hours
    sig = email.signature
    comp = config.compliance
    rules_setting = (config.writer.email_rules or "").strip()
    try:
        rules_text = read_user_text(_rules_path(root))
    except OSError:
        rules_text = ""
    return {
        "sending": {
            "provider": email.provider,
            "providers": list(PROVIDERS),
            "max_daily_sends": email.max_daily_sends,
            "require_approval": email.require_approval,
            "sender_name": config.persona.name,
            "sender_email": config.persona.email,
        },
        "schedule": {
            "quiet_start": quiet.start,
            "quiet_end": quiet.end,
            "timezone": quiet.timezone,
            "heartbeat_interval_minutes": config.usage.heartbeat_interval_minutes,
            "timezones": COMMON_TIMEZONES,
        },
        "footer": {
            "postal_address": comp.postal_address,
            "opt_out_line": comp.opt_out_line,
            "default_opt_out_line": DEFAULT_OPT_OUT_LINE,
            "do_not_contact": list(comp.do_not_contact or []),
        },
        "signature": {
            "has_logo": bool(sig.logo),
            "logo": sig.logo,
            "width": sig.width,
            "alt": sig.alt,
            "link": sig.link,
            "max_bytes": MAX_LOGO_BYTES,
        },
        "template": {
            "enabled": bool(rules_setting),
            "file": rules_setting or RULES_FILE,
            "text": rules_text,
            "starter": STARTER_TEMPLATE,
            "max_chars": MAX_EMAIL_RULES_CHARS,
        },
    }


# ── Writing ───────────────────────────────────────────────────────────────

def _load(config_file: Path) -> tuple[str, dict]:
    raw = read_user_text(config_file)
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise SetupError(f"{config_file.name} isn't a settings file Chirayu Power can edit")
    return raw, data


def _branch(data: dict, *path: str) -> dict:
    node = data
    for key in path:
        nxt = node.get(key)
        if nxt is None:
            nxt = node[key] = {}
        if not isinstance(nxt, dict):
            raise SetupError(f"{'.'.join(path)} isn't a section Chirayu Power can edit")
        node = nxt
    return node


def _friendly(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        where = ".".join(str(x) for x in err.get("loc", ()))
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{where}: {msg}" if where else msg)
    return "; ".join(parts) or "the settings aren't valid"


def write_validated(config_file: Path, raw: str, data: dict) -> None:
    """Check ``data`` loads as a complete Sellbird config, keep a .bak of
    ``raw`` (the file as it was), then write ``data``."""
    try:
        SellbirdConfig(**data)
    except ValidationError as e:
        raise SetupError(_friendly(e)) from None
    config_file.with_name(config_file.name + ".bak").write_text(raw, encoding="utf-8")
    config_file.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


def _text(value, limit: int = MAX_TEXT) -> str:
    if isinstance(value, (dict, list)):
        raise SetupError("expected text")
    return str(value if value is not None else "").strip()[:limit]


def _int(value, name: str, lo: int, hi: int) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise SetupError(f"{name} must be a whole number") from None
    if not lo <= n <= hi:
        raise SetupError(f"{name} must be between {lo} and {hi}")
    return n


def _lines(value) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split("\n")
    return [" ".join(str(i).split())[:MAX_TEXT] for i in items if str(i).strip()][:MAX_ITEMS]


def save(config_file: Path, root: Path, section: str, fields: dict) -> str:
    """Save one card of the Email setup tab. Returns a message for the user."""
    if not isinstance(fields, dict):
        raise SetupError("nothing to save")
    raw, data = _load(config_file)

    if section == "sending":
        email = _branch(data, "channels", "email")
        if "provider" in fields:
            provider = _text(fields["provider"]).lower()
            if provider not in PROVIDERS:
                raise SetupError(f"the mailbox type must be one of {', '.join(PROVIDERS)}")
            email["provider"] = provider
        if "max_daily_sends" in fields:
            email["max_daily_sends"] = _int(fields["max_daily_sends"], "Daily limit", 0, 2000)
        if "sender_email" in fields:
            addr = _text(fields["sender_email"], 254)
            if addr and ("@" not in addr or " " in addr):
                raise SetupError("the sender email doesn't look like an email address")
            _branch(data, "persona")["email"] = addr
        message = "Saved. Chirayu Power uses it from its next cycle."

    elif section == "schedule":
        quiet = _branch(data, "usage", "quiet_hours")
        for key, target in (("quiet_start", "start"), ("quiet_end", "end"), ("timezone", "timezone")):
            if key in fields:
                quiet[target] = _text(fields[key], 64)
        if "heartbeat_interval_minutes" in fields:
            _branch(data, "usage")["heartbeat_interval_minutes"] = _int(
                fields["heartbeat_interval_minutes"], "Check every", 1, 1440)
        message = "Saved. Restart the loop on the Controls tab for a new check interval to apply."

    elif section == "footer":
        comp = _branch(data, "compliance")
        if "postal_address" in fields:
            comp["postal_address"] = _text(fields["postal_address"], 500)
        if "opt_out_line" in fields:
            comp["opt_out_line"] = _text(fields["opt_out_line"], 500)
        if "do_not_contact" in fields:
            comp["do_not_contact"] = [x.lower() for x in _lines(fields["do_not_contact"])]
        message = "Saved. Every cold email sent from now on carries it."

    elif section == "signature":
        sig = _branch(data, "channels", "email", "signature")
        if "width" in fields:
            sig["width"] = _int(fields["width"], "Logo width", 16, 600)
        if "alt" in fields:
            sig["alt"] = _text(fields["alt"], 200)
        if "link" in fields:
            sig["link"] = _text(fields["link"], 500)
        message = "Saved."

    elif section == "template":
        writer = _branch(data, "writer")
        enabled = bool(fields.get("enabled"))
        if "text" in fields:
            text = str(fields.get("text") or "").replace("\r\n", "\n").strip()
            if len(text) > MAX_EMAIL_RULES_CHARS:
                raise SetupError(f"the template is {len(text):,} characters; the limit is "
                                 f"{MAX_EMAIL_RULES_CHARS:,}")
            if enabled and not text:
                raise SetupError("the template is empty. Write it, or turn it off")
            path = _rules_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n" if text else "", encoding="utf-8")
        writer["email_rules"] = RULES_FILE if enabled else ""
        message = ("Saved. New emails are written with your template." if enabled
                   else "Saved. New emails use the built-in style.")

    else:
        raise SetupError(f"'{section}' can't be edited here")

    write_validated(config_file, raw, data)
    return message


# ── Logo image ────────────────────────────────────────────────────────────

_MAGIC = ((b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
          (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
          (b"GIF87a", ".gif", "image/gif"),
          (b"GIF89a", ".gif", "image/gif"))


def image_type(data: bytes) -> tuple[str, str] | None:
    for magic, ext, mime in _MAGIC:
        if data.startswith(magic):
            return ext, mime
    return None


def save_logo(config_file: Path, root: Path, b64: str) -> str:
    """Store an uploaded logo (base64) under assets/email and point the
    signature at it. Refuses anything that isn't a small PNG, JPEG or GIF,
    and anything the email signature itself would refuse to send."""
    try:
        blob = base64.b64decode(str(b64 or "").split(",")[-1], validate=True)
    except (ValueError, TypeError):
        raise SetupError("the upload wasn't a readable file") from None
    if not blob:
        raise SetupError("the file is empty")
    if len(blob) > MAX_LOGO_BYTES:
        raise SetupError(f"the image is {len(blob) // 1000} KB; keep it under "
                         f"{MAX_LOGO_BYTES // 1000} KB (resize it to about 400 px wide)")
    kind = image_type(blob)
    if not kind:
        raise SetupError("use a PNG, JPEG or GIF image")
    ext, _mime = kind

    folder = Path(root) / LOGO_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"logo{ext}"
    previous = {p: p.read_bytes() for p in folder.glob("logo.*") if p.is_file()}
    for p in previous:
        p.unlink()
    target.write_bytes(blob)

    raw, data = _load(config_file)
    sig = _branch(data, "channels", "email", "signature")
    sig["logo"] = f"{LOGO_DIR}/{target.name}"
    try:
        # Check the file the way the sender will, by its full path.
        trial = SellbirdConfig(**data).model_copy(deep=True)
        trial.channels.email.signature.logo = str(target.resolve())
        load_signature(trial)
        write_validated(config_file, raw, data)
    except (SignatureError, SetupError, ValidationError) as e:
        target.unlink(missing_ok=True)
        for p, content in previous.items():
            p.write_bytes(content)
        msg = _friendly(e) if isinstance(e, ValidationError) else str(e)
        raise SetupError(f"that image can't be used: {msg}") from None
    return "Logo saved. It appears under every email from now on."


def remove_logo(config_file: Path, root: Path) -> str:
    raw, data = _load(config_file)
    sig = _branch(data, "channels", "email", "signature")
    sig["logo"] = ""
    write_validated(config_file, raw, data)
    for p in (Path(root) / LOGO_DIR).glob("logo.*"):
        p.unlink(missing_ok=True)
    return "Logo removed. Emails go out as plain text again."


def logo_file(config, root: Path) -> tuple[bytes, str] | None:
    """The configured logo's bytes and type, for the dashboard preview."""
    logo = (config.channels.email.signature.logo or "").strip()
    if not logo:
        return None
    path = Path(logo).expanduser()
    if not path.is_absolute():
        path = Path(root) / path
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    kind = image_type(blob)
    return (blob, kind[1]) if kind else None

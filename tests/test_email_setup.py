"""Email setup tab: every card saves to the config, and nothing invalid is written."""

import base64
import struct
import zlib

import pytest
import yaml

from sellbird import email_setup as es
from sellbird.config import load_config
from sellbird.offer import save_company

BASE = {
    "persona": {"name": "Sam", "company": "Example Solar", "role": "Sales", "email": "sam@example.com",
                "linkedin": "", "tone": "plain"},
    "product": {"name": "Rooftop solar", "description": "Solar plants", "pricing": "",
                "key_benefits": [], "objection_responses": {}},
    "icp": {"industries": ["Textile mills"], "company_size": "50-500",
            "titles": [f"Title {i}" for i in range(46)], "geography": ["Pune, India"]},
}


def _png(w=40, h=20):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def setup(tmp_path):
    cfg = tmp_path / "sellbird.local.yaml"
    cfg.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    return cfg, tmp_path


def test_sending_schedule_and_footer_save(setup):
    cfg, root = setup
    es.save(cfg, root, "sending", {"provider": "microsoft", "max_daily_sends": "25",
                                   "sender_email": "outreach@example.com"})
    es.save(cfg, root, "schedule", {"quiet_start": "21:00", "quiet_end": "08:00",
                                    "timezone": "Asia/Kolkata", "heartbeat_interval_minutes": 30})
    es.save(cfg, root, "footer", {"postal_address": "1 Main Road, Pune 411001",
                                  "do_not_contact": ["Rival.example", ""]})
    c = load_config(str(cfg))
    assert c.channels.email.provider == "microsoft" and c.channels.email.max_daily_sends == 25
    assert c.persona.email == "outreach@example.com"
    assert c.usage.quiet_hours.timezone == "Asia/Kolkata" and c.usage.heartbeat_interval_minutes == 30
    assert c.compliance.postal_address.startswith("1 Main Road")
    assert c.compliance.do_not_contact == ["rival.example"]
    assert (cfg.with_name(cfg.name + ".bak")).exists()


def test_invalid_values_are_refused_and_file_untouched(setup):
    cfg, root = setup
    before = cfg.read_text(encoding="utf-8")
    with pytest.raises(es.SetupError):
        es.save(cfg, root, "schedule", {"timezone": "Mars/Base"})
    with pytest.raises(es.SetupError):
        es.save(cfg, root, "sending", {"provider": "carrier-pigeon"})
    with pytest.raises(es.SetupError):
        es.save(cfg, root, "signature", {"link": "javascript:alert(1)"})
    assert cfg.read_text(encoding="utf-8") == before


def test_template_on_off(setup):
    cfg, root = setup
    es.save(cfg, root, "template", {"enabled": True, "text": "# Rules\n- Short."})
    assert load_config(str(cfg)).writer.email_rules == es.RULES_FILE
    assert (root / es.RULES_FILE).read_text(encoding="utf-8").startswith("# Rules")
    with pytest.raises(es.SetupError):
        es.save(cfg, root, "template", {"enabled": True, "text": "   "})
    es.save(cfg, root, "template", {"enabled": False, "text": "# Rules\n- Short."})
    assert load_config(str(cfg)).writer.email_rules == ""


def test_logo_upload_and_remove(setup):
    cfg, root = setup
    es.save_logo(cfg, root, "data:image/png;base64," + base64.b64encode(_png()).decode())
    c = load_config(str(cfg))
    assert c.channels.email.signature.logo == "assets/email/logo.png"
    blob, mime = es.logo_file(c, root)
    assert mime == "image/png" and blob.startswith(b"\x89PNG")
    es.remove_logo(cfg, root)
    assert load_config(str(cfg)).channels.email.signature.logo == ""
    assert not list((root / es.LOGO_DIR).glob("logo.*"))


def test_logo_refuses_non_images_and_big_files(setup):
    cfg, root = setup
    with pytest.raises(es.SetupError):
        es.save_logo(cfg, root, base64.b64encode(b"<svg></svg>").decode())
    with pytest.raises(es.SetupError):
        es.save_logo(cfg, root, base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (es.MAX_LOGO_BYTES + 1)).decode())
    assert load_config(str(cfg)).channels.email.signature.logo == ""


def test_company_keeps_long_lists_and_saves_search_phrases(setup):
    cfg, _root = setup
    titles = [f"Title {i}" for i in range(46)]
    save_company(cfg, "icp", {"titles": titles,
                              "keyword_variants": {"Textile mills": ["spinning mill", "ginning", ""]},
                              "hiring_signals": ["Energy Manager"]})
    save_company(cfg, "persona", {"email": "outreach@example.com"})
    c = load_config(str(cfg))
    assert c.icp.titles == titles
    assert c.icp.keyword_variants == {"Textile mills": ["spinning mill", "ginning"]}
    assert c.icp.hiring_signals == ["Energy Manager"]
    assert c.persona.email == "outreach@example.com"
    with pytest.raises(ValueError):
        save_company(cfg, "persona", {"email": "not an address"})


def test_osm_knows_industrial_buyers():
    from sellbird.collectors.discover import PROVIDERS
    osm = next(p for p in PROVIDERS.values() if hasattr(p, "_tags"))
    assert "amenity=hospital" in osm._tags("Healthcare (multi-specialty hospitals)")
    assert osm._tags("Hospitality & Retail (hotels, resorts, malls)") == ["tourism=hotel"]
    assert "amenity=college" in osm._tags("Education (engineering colleges, schools)")
    assert "man_made=works" in osm._tags("Textile & Spinning Mills")
    assert osm._tags("small offices") == []

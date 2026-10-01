"""The Revive bootstrap files cover every Revive table the Copilot uses, and
the bootstrapped admin can never log in."""
from __future__ import annotations

import re
from pathlib import Path

from src.revive_data.admin_fixtures import _NO_LOGIN_PASSWORD

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "src" / "revive_data" / "revive_mysql_schema.sql"
BASE_ROWS = ROOT / "src" / "revive_data" / "revive_base_rows.sql"


def _tables_named_in_src() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        names |= set(re.findall(r"\brv_[a-z_]+\b", path.read_text()))
    return names


def test_every_table_in_src_has_a_definition():
    defined = set(re.findall(r"CREATE TABLE IF NOT EXISTS `(rv_[a-z_]+)`", SCHEMA.read_text()))
    assert _tables_named_in_src() - defined == set()


def test_admin_cannot_log_in():
    rows = BASE_ROWS.read_text()
    admin = re.search(r"\(1, 'Administrator', '[^']*', 'admin', '([^']*)'", rows)
    assert admin and admin.group(1) == _NO_LOGIN_PASSWORD


def test_no_real_contact_details_or_hashes():
    text = SCHEMA.read_text() + BASE_ROWS.read_text()
    assert "$2y$" not in text  # bcrypt hash
    assert set(re.findall(r"[\w.+-]+@([\w-]+\.[\w.]+)", text)) <= {"example.com"}

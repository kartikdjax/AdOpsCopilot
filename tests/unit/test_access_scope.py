"""Scope validation and the role -> scope mapping, without any database.
tests/live/test_access_control.py checks that the scope is actually enforced."""
from __future__ import annotations

import pytest

from src.api.auth import user_scope
from src.semantic.access import ADMIN, Scope


@pytest.mark.parametrize("make_scope", [
    lambda: Scope("manager"),
    lambda: Scope("superuser"),
    lambda: Scope("admin", 2),
    lambda: Scope.from_meta(None),
    lambda: Scope.from_meta({"copilot_scope": {"role": "root"}}),
], ids=["manager-without-agency", "unknown-role", "admin-with-agency", "no-meta", "forged-role"])
def test_invalid_scope_is_rejected(make_scope):
    with pytest.raises(PermissionError):
        make_scope()


def test_scope_round_trips_through_request_meta():
    scope = Scope("manager", 2)
    assert Scope.from_meta(scope.to_meta()) == scope


def test_user_role_maps_to_scope():
    assert user_scope({"role": "admin", "agency_id": None}) == ADMIN
    assert user_scope({"role": "manager", "agency_id": 2}) == Scope("manager", 2)
    assert user_scope({"role": "manager", "agency_id": None}) is None
    assert user_scope({"role": "pending", "agency_id": None}) is None

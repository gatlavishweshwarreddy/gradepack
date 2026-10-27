import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "starter"))

from roles import Role
from permissions import has_permission
import pytest


VIEWER = Role("viewer", frozenset(["read"]))
EDITOR = Role("editor", frozenset(["read", "write"]))
ADMIN  = Role("admin",  frozenset(["read", "write", "delete"]))
READ_WRITE = Role("read_write_role", frozenset(["read_write"]))


def test_user_with_permission():
    assert has_permission([VIEWER], "read") is True


def test_user_without_permission():
    assert has_permission([VIEWER], "write") is False


def test_multi_role_has_permission():
    assert has_permission([VIEWER, EDITOR], "write") is True


def test_empty_roles():
    assert has_permission([], "read") is False


def test_exact_match_required():
    assert has_permission([READ_WRITE_ROLE], "read") is False


def test_exact_match_required_write():
    assert has_permission([READ_WRITE_ROLE], "write") is False


def test_exact_full_permission_matches():
    assert has_permission([READ_WRITE_ROLE], "read_write") is True


def test_delete_not_in_editor():
    assert has_permission([EDITOR], "delete") is False


def test_admin_has_delete():
    assert has_permission([ADMIN], "delete") is True


READ_WRITE_ROLE = Role("rw", frozenset(["read_write"]))

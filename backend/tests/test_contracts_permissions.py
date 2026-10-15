# S04 tests — permission model.

import pytest
from seraphim.contracts.permissions import Permission, validate_permission


class TestValidatePermission:
    @pytest.mark.parametrize(
        "perm",
        [
            "filesystem.read",
            "filesystem.write",
            "shell.execute",
            "network.http.get",
            "application",
            "a.b.c.d",
        ],
    )
    def test_valid_permissions(self, perm: str) -> None:
        assert validate_permission(perm) == perm

    @pytest.mark.parametrize(
        "perm",
        [
            "",
            "UPPER.case",
            "has space",
            "has-dash.here",
            ".leading",
            "trailing.",
            "a.b.c.d.e",
        ],
    )
    def test_invalid_permissions(self, perm: str) -> None:
        with pytest.raises(ValueError, match="Invalid permission"):
            validate_permission(perm)

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError):
            validate_permission(42)  # type: ignore[arg-type]


class TestPermissionConstruction:
    def test_minimal(self) -> None:
        p = Permission(name="filesystem.read")
        assert p.name == "filesystem.read"
        assert p.scope == ""

    def test_with_scope(self) -> None:
        p = Permission(name="filesystem.read", scope="/projects/myapp")
        assert str(p) == "filesystem.read(/projects/myapp)"

    def test_str_without_scope(self) -> None:
        p = Permission(name="shell.execute")
        assert str(p) == "shell.execute"

    def test_frozen(self) -> None:
        p = Permission(name="a.b")
        with pytest.raises(AttributeError):
            p.name = "c.d"  # type: ignore[misc]

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid permission"):
            Permission(name="INVALID")


class TestPermissionSerialization:
    def test_to_dict_minimal(self) -> None:
        p = Permission(name="filesystem.read")
        d = p.to_dict()
        assert d == {"name": "filesystem.read"}

    def test_to_dict_with_scope(self) -> None:
        p = Permission(name="filesystem.read", scope="/root")
        d = p.to_dict()
        assert d == {"name": "filesystem.read", "scope": "/root"}

    def test_round_trip(self) -> None:
        original = Permission(name="network.http.get", scope="example.com")
        restored = Permission.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.scope == original.scope

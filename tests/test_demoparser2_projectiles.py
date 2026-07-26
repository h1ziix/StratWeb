from __future__ import annotations

from typing import Any

from stratweb.adapters.parsers.demoparser2_projectiles import extract_projectiles
from stratweb.spatial.projectiles import (
    PROJECTILE_REQUESTED_PROPERTIES,
    ProjectileAvailability,
    ProjectileLifecycle,
    ProjectileType,
    UtilityEffectType,
)


class FakeFrame:
    def __init__(self, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
        self._rows = rows
        self.columns = columns

    def sort_values(self, names: list[str], *, kind: str) -> FakeFrame:
        assert kind == "stable"
        return FakeFrame(
            sorted(self._rows, key=lambda row: tuple(str(row.get(name)) for name in names)),
            self.columns,
        )

    def itertuples(self, *, index: bool, name: None) -> list[tuple[object, ...]]:
        assert index is False and name is None
        return [tuple(row.get(column) for column in self.columns) for row in self._rows]

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return self._rows


class ProjectileBackend:
    def __init__(self) -> None:
        self.extra: tuple[str, ...] = ()
        self.grenades_only: bool | None = None

    def list_game_events(self) -> list[str]:
        return [
            "weapon_fire",
            "smokegrenade_detonate",
            "smokegrenade_expired",
        ]

    def parse_events(self, names: list[str]) -> list[tuple[str, FakeFrame]]:
        records = {
            "weapon_fire": [
                {"tick": 108, "user_steamid": 76561198000000001, "weapon": "smokegrenade"}
            ],
            "smokegrenade_detonate": [
                {
                    "tick": 114,
                    "entityid": 77,
                    "user_steamid": 76561198000000001,
                    "x": 14.0,
                    "y": 24.0,
                    "z": 3.0,
                }
            ],
            "smokegrenade_expired": [
                {"tick": 130, "entityid": 77, "user_steamid": 76561198000000001}
            ],
        }
        return [
            (name, FakeFrame(records.get(name, []), tuple(records.get(name, [{}])[0].keys())))
            for name in names
            if records.get(name)
        ]

    def parse_grenades(self, *, extra: list[str], grenades: bool) -> FakeFrame:
        self.extra = tuple(extra)
        self.grenades_only = grenades
        columns = (
            "grenade_type",
            "grenade_entity_id",
            "x",
            "y",
            "z",
            "tick",
            "steamid",
            "name",
            "Grenade.m_nBounces",
            "Grenade.m_vInitialVelocity",
        )
        rows = [
            {
                "grenade_type": "CSmokeGrenadeProjectile",
                "grenade_entity_id": 7,
                "x": float(tick - 100),
                "y": float(tick - 90),
                "z": 3.0,
                "tick": tick,
                "steamid": 76561198000000001,
                "name": "Alpha",
                "Grenade.m_nBounces": 0 if tick < 112 else 1,
                "Grenade.m_vInitialVelocity": (100.0, 50.0, 20.0),
            }
            for tick in range(110, 115)
        ]
        return FakeFrame(rows, columns)


def test_projectile_adapter_uses_audited_contract_and_typed_lifecycle() -> None:
    backend = ProjectileBackend()

    result = extract_projectiles(backend)

    assert backend.extra == PROJECTILE_REQUESTED_PROPERTIES
    assert backend.grenades_only is False
    assert len(result.tracks) == 1
    track = result.tracks[0]
    assert track.projectile_type is ProjectileType.SMOKE
    assert track.thrown_tick == 108
    assert track.terminal_tick == 114
    assert "terminal_event_associated_by_owner_type_tick_and_position" in track.warnings
    assert [point.tick for point in track.points] == [110, 112, 114]
    assert track.points[1].lifecycle is ProjectileLifecycle.BOUNCED
    assert track.points[-1].lifecycle is ProjectileLifecycle.DETONATED
    assert track.availability is ProjectileAvailability.AVAILABLE
    assert result.effects[0].effect_type is UtilityEffectType.SMOKE
    assert result.effects[0].end_tick == 130
    assert result.capabilities.positions.status is ProjectileAvailability.AVAILABLE
    assert result.capabilities.initial_velocity.status is ProjectileAvailability.AVAILABLE


def test_projectile_failure_does_not_fail_player_spatial_extraction() -> None:
    class FailingBackend(ProjectileBackend):
        def parse_grenades(self, *, extra: list[str], grenades: bool) -> FakeFrame:
            raise RuntimeError("broken projectile entity table")

    result = extract_projectiles(FailingBackend())

    assert result.tracks == ()
    assert result.capabilities.positions.status is ProjectileAvailability.UNAVAILABLE
    assert result.warnings[0].startswith("projectile_extraction_failed:RuntimeError")

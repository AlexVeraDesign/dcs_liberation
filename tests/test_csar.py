from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

from dcs.mapping import Point
from dcs.terrain import Caucasus

from game.ato import FlightType
from game.csar import CsarManager, CsarResolution, CsarTarget
from game.db.gamedb import GameDb
from game.server.tgos.models import TgoJs
from game.squadrons.pilot import Pilot, PilotStatus
from game.squadrons.squadron import Squadron
from game.unitmap import FlyingUnit


def point(x: float, y: float) -> Point:
    return Point(x, y, Caucasus())


@dataclass
class FakeControlPoint:
    name: str
    position: Point
    captured: bool

    def is_friendly(self, to_player: bool) -> bool:
        return self.captured == to_player


@dataclass
class FakeTheater:
    controlpoints: list[FakeControlPoint]
    sea: bool = False

    def is_in_sea(self, position: Point) -> bool:
        return self.sea


@dataclass
class FakeSquadron:
    name: str = "Fake Squadron"
    player: bool = True
    available_pilots: list[Pilot] = field(default_factory=list)
    location: FakeControlPoint = field(
        default_factory=lambda: FakeControlPoint("Home", point(0, 0), True)
    )

    def __str__(self) -> str:
        return self.name


def game_with_cps(*cps: FakeControlPoint, sea: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        turn=0,
        simulation_time=datetime(2026, 8, 23, 12, 0),
        theater=FakeTheater(list(cps), sea=sea),
        db=GameDb(),
        point_in_world=lambda x, y: point(x, y),
        settings=SimpleNamespace(
            invulnerable_player_pilots=False,
            csar_friendly_recovery_radius=20,
            csar_enemy_capture_radius=20,
            csar_pickup_radius=300,
            csar_grouping_radius=10,
        ),
    )


def flying_unit(pilot: Pilot, squadron: FakeSquadron) -> FlyingUnit:
    flight = SimpleNamespace(
        squadron=squadron,
        unit_type=SimpleNamespace(helicopter=False),
        package=SimpleNamespace(target=SimpleNamespace(position=point(1000, 0))),
    )
    return FlyingUnit(flight, pilot)


def test_friendly_cp_automatic_recovery() -> None:
    pilot = Pilot("Pilot")
    squadron = FakeSquadron()
    game = game_with_cps(FakeControlPoint("Friendly", point(0, 0), True))

    target = CsarManager().add_aircraft_survivor(
        game, flying_unit(pilot, squadron), point(1000, 0)
    )

    assert target is None
    assert pilot.status is PilotStatus.Active
    assert pilot in squadron.available_pilots


def test_enemy_cp_automatic_capture() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(FakeControlPoint("Enemy", point(0, 0), False))

    target = CsarManager().add_aircraft_survivor(
        game, flying_unit(pilot, FakeSquadron()), point(1000, 0)
    )

    assert target is None
    assert pilot.status is PilotStatus.Dead


def test_overlapping_cp_radii_choose_nearest() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(
        FakeControlPoint("Friendly", point(2000, 0), True),
        FakeControlPoint("Enemy", point(1000, 0), False),
    )

    resolution = CsarManager().resolve_by_control_points(
        game,
        CsarTarget(
            pilot=pilot,
            squadron=FakeSquadron(),
            position=point(0, 0),
            turn_created=0,
            sea=False,
        ),
    )

    assert resolution is CsarResolution.CAPTURED


def test_deep_enemy_territory_outside_cp_radii_creates_csar() -> None:
    pilot = Pilot("Pilot")
    squadron = FakeSquadron(available_pilots=[pilot])
    game = game_with_cps(FakeControlPoint("Enemy", point(100000, 0), False))
    manager = CsarManager()

    target = manager.add_aircraft_survivor(
        game, flying_unit(pilot, squadron), point(0, 0)
    )

    assert target is not None
    assert pilot.status is PilotStatus.MIA
    assert pilot not in squadron.available_pilots
    assert target in manager.targets


def test_enemy_aircraft_survivor_does_not_create_csar_target() -> None:
    pilot = Pilot("Enemy")
    squadron = FakeSquadron(player=False)
    game = game_with_cps()
    manager = CsarManager()

    target = manager.add_aircraft_survivor(
        game, flying_unit(pilot, squadron), point(0, 0)
    )

    assert target is None
    assert pilot.status is PilotStatus.Dead
    assert manager.targets == []


def test_enemy_helicopter_loss_does_not_create_csar_target() -> None:
    pilot = Pilot("Enemy")
    squadron = FakeSquadron(player=False)
    game = game_with_cps()
    manager = CsarManager()

    target = manager.add_helicopter_loss(
        game, flying_unit(pilot, squadron), point(0, 0)
    )

    assert target is None
    assert pilot.status is PilotStatus.Dead
    assert manager.targets == []


def test_configured_friendly_recovery_radius_is_respected() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(FakeControlPoint("Friendly", point(0, 0), True))
    game.settings.csar_friendly_recovery_radius = 1
    manager = CsarManager()

    target = manager.add_aircraft_survivor(
        game, flying_unit(pilot, FakeSquadron()), point(5000, 0)
    )

    assert target is not None
    assert pilot.status is PilotStatus.MIA


def test_configured_enemy_capture_radius_is_respected() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(FakeControlPoint("Enemy", point(0, 0), False))
    game.settings.csar_enemy_capture_radius = 1
    manager = CsarManager()

    target = manager.add_aircraft_survivor(
        game, flying_unit(pilot, FakeSquadron()), point(5000, 0)
    )

    assert target is not None
    assert pilot.status is PilotStatus.MIA


def test_nearby_csar_targets_are_grouped_at_center_point() -> None:
    game = game_with_cps()
    manager = CsarManager()
    squadron = FakeSquadron()
    first = Pilot("Pilot A")
    second = Pilot("Pilot B")

    first_target = manager.add_aircraft_survivor(
        game, flying_unit(first, squadron), point(0, 0)
    )
    second_target = manager.add_aircraft_survivor(
        game, flying_unit(second, squadron), point(1000, 0)
    )

    assert first_target is not None
    assert second_target is first_target
    assert len(manager.targets) == 1
    assert len(first_target.survivors) == 2
    assert first_target.position.x == 500
    assert first_target.position.y == 0
    assert first_target.name == "CSAR: 2 pilots"


def test_csar_grouping_uses_connected_components() -> None:
    game = game_with_cps()
    manager = CsarManager()
    squadron = FakeSquadron()
    eight_nm = 8 * 1852

    manager.add_aircraft_survivor(
        game, flying_unit(Pilot("Pilot A"), squadron), point(0, 0)
    )
    manager.add_aircraft_survivor(
        game, flying_unit(Pilot("Pilot B"), squadron), point(eight_nm, 0)
    )
    manager.add_aircraft_survivor(
        game, flying_unit(Pilot("Pilot C"), squadron), point(eight_nm * 2, 0)
    )

    assert len(manager.targets) == 1
    assert len(manager.targets[0].survivors) == 3
    assert manager.targets[0].position.x == eight_nm


def test_csar_map_label_uses_squadrons_not_bases() -> None:
    game = game_with_cps()
    manager = CsarManager()
    lhd_squadron = FakeSquadron(
        name="LHD Squadron",
        location=FakeControlPoint("Juan Carlos I", point(0, 0), True),
    )
    vaziani_squadron = FakeSquadron(
        name="Vaziani Squadron", location=FakeControlPoint("Vaziani", point(0, 0), True)
    )

    target = manager.add_aircraft_survivor(
        game, flying_unit(Pilot("Pilot A"), lhd_squadron), point(0, 0)
    )
    manager.add_aircraft_survivor(
        game, flying_unit(Pilot("Pilot B"), vaziani_squadron), point(1000, 0)
    )

    assert target is not None
    tgo = TgoJs.for_tgo(target)
    assert tgo.control_point_name == "LHD Squadron, Vaziani Squadron"


def test_land_csar_expiration_kills_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps()
    manager = CsarManager()
    target = CsarTarget(pilot, FakeSquadron(), point(0, 0), 0, sea=False)
    pilot.mark_mia()
    manager.targets.append(target)
    game.db.tgos.add(target.id, target)
    game.turn = 8

    manager.process_turn(game)

    assert pilot.status is PilotStatus.MIA
    assert target in manager.targets

    game.turn = 9

    manager.process_turn(game)

    assert pilot.status is PilotStatus.Dead
    assert target not in manager.targets


def test_sea_csar_expiration_kills_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(sea=True)
    manager = CsarManager()
    target = CsarTarget(pilot, FakeSquadron(), point(0, 0), 0, sea=True)
    pilot.mark_mia()
    manager.targets.append(target)
    game.db.tgos.add(target.id, target)
    game.turn = 1

    manager.process_turn(game)

    assert pilot.status is PilotStatus.MIA
    assert target in manager.targets

    game.turn = 2

    manager.process_turn(game)

    assert pilot.status is PilotStatus.Dead


def test_turns_remaining_include_first_playable_turn() -> None:
    target = CsarTarget(Pilot("Pilot"), FakeSquadron(), point(0, 0), 18, sea=False)

    assert target.turns_remaining(19) == 8
    assert target.turns_remaining(20) == 7


def test_mia_pilots_do_not_open_replenishment_slots() -> None:
    active_pilots = [Pilot(f"Active {idx}") for idx in range(3)]
    mia_pilot = Pilot("MIA Pilot", status=PilotStatus.MIA)
    squadron = object.__new__(Squadron)
    squadron.current_roster = [*active_pilots, mia_pilot]
    squadron.settings = SimpleNamespace(
        enable_squadron_pilot_limits=True,
        squadron_pilot_limit=4,
        squadron_replenishment_rate=1,
    )

    assert squadron.replenish_count == 0


def test_pickup_alive_recovers_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps()
    manager = CsarManager()
    squadron = FakeSquadron()
    target = CsarTarget(pilot, squadron, point(0, 0), 0, sea=False)
    pilot.mark_mia()
    manager.targets.append(target)
    game.db.tgos.add(target.id, target)

    manager.handle_pickup_results(game, {target.id: "Rescue 1-1"}, set())

    assert pilot.status is PilotStatus.Active
    assert pilot in squadron.available_pilots
    assert target not in manager.targets


def test_pickup_destroyed_kills_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps()
    manager = CsarManager()
    target = CsarTarget(pilot, FakeSquadron(), point(0, 0), 0, sea=False)
    pilot.mark_mia()
    manager.targets.append(target)
    game.db.tgos.add(target.id, target)

    manager.handle_pickup_results(game, {target.id: "Rescue 1-1"}, {"Rescue 1-1"})

    assert pilot.status is PilotStatus.Dead
    assert target not in manager.targets


def test_no_pickup_remains_mia() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps()
    manager = CsarManager()
    target = CsarTarget(pilot, FakeSquadron(), point(0, 0), 0, sea=False)
    pilot.mark_mia()
    manager.targets.append(target)

    manager.handle_pickup_results(game, {}, set())

    assert pilot.status is PilotStatus.MIA
    assert target in manager.targets


def test_csar_target_mission_types() -> None:
    target = CsarTarget(Pilot("Pilot"), FakeSquadron(), point(0, 0), 0, sea=False)

    assert list(target.mission_types(for_player=True)) == [
        FlightType.CSAR,
        FlightType.TARCAP,
        FlightType.ESCORT,
        FlightType.SWEEP,
    ]

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from dcs.mapping import Point

from game.ato import FlightType
from game.csar import CsarManager, CsarResolution, CsarTarget
from game.db.gamedb import GameDb
from game.squadrons.pilot import Pilot, PilotStatus
from game.unitmap import FlyingUnit


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
    player: bool = True
    available_pilots: list[Pilot] = field(default_factory=list)
    location: FakeControlPoint = field(
        default_factory=lambda: FakeControlPoint("Home", Point(0, 0), True)
    )


def game_with_cps(*cps: FakeControlPoint, sea: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        turn=0,
        theater=FakeTheater(list(cps), sea=sea),
        db=GameDb(),
        settings=SimpleNamespace(invulnerable_player_pilots=False),
    )


def flying_unit(pilot: Pilot, squadron: FakeSquadron) -> FlyingUnit:
    flight = SimpleNamespace(
        squadron=squadron,
        unit_type=SimpleNamespace(helicopter=False),
        package=SimpleNamespace(target=SimpleNamespace(position=Point(1000, 0))),
    )
    return FlyingUnit(flight, pilot)


def test_friendly_cp_automatic_recovery() -> None:
    pilot = Pilot("Pilot")
    squadron = FakeSquadron()
    game = game_with_cps(FakeControlPoint("Friendly", Point(0, 0), True))

    target = CsarManager().add_aircraft_survivor(
        game, flying_unit(pilot, squadron), Point(1000, 0)
    )

    assert target is None
    assert pilot.status is PilotStatus.Active
    assert pilot in squadron.available_pilots


def test_enemy_cp_automatic_capture() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(FakeControlPoint("Enemy", Point(0, 0), False))

    target = CsarManager().add_aircraft_survivor(
        game, flying_unit(pilot, FakeSquadron()), Point(1000, 0)
    )

    assert target is None
    assert pilot.status is PilotStatus.Dead


def test_overlapping_cp_radii_choose_nearest() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(
        FakeControlPoint("Friendly", Point(2000, 0), True),
        FakeControlPoint("Enemy", Point(1000, 0), False),
    )

    resolution = CsarManager().resolve_by_control_points(
        game,
        CsarTarget(
            pilot=pilot,
            squadron=FakeSquadron(),
            position=Point(0, 0),
            turn_created=0,
            sea=False,
        ),
    )

    assert resolution is CsarResolution.CAPTURED


def test_deep_enemy_territory_outside_cp_radii_creates_csar() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(FakeControlPoint("Enemy", Point(100000, 0), False))
    manager = CsarManager()

    target = manager.add_aircraft_survivor(
        game, flying_unit(pilot, FakeSquadron()), Point(0, 0)
    )

    assert target is not None
    assert pilot.status is PilotStatus.MIA
    assert target in manager.targets


def test_land_csar_expiration_kills_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps()
    manager = CsarManager()
    target = CsarTarget(pilot, FakeSquadron(), Point(0, 0), 0, sea=False)
    pilot.mark_mia()
    manager.targets.append(target)
    game.db.tgos.add(target.id, target)
    game.turn = 8

    manager.process_turn(game)

    assert pilot.status is PilotStatus.Dead
    assert target not in manager.targets


def test_sea_csar_expiration_kills_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps(sea=True)
    manager = CsarManager()
    target = CsarTarget(pilot, FakeSquadron(), Point(0, 0), 0, sea=True)
    pilot.mark_mia()
    manager.targets.append(target)
    game.db.tgos.add(target.id, target)
    game.turn = 1

    manager.process_turn(game)

    assert pilot.status is PilotStatus.Dead


def test_pickup_alive_recovers_pilot() -> None:
    pilot = Pilot("Pilot")
    game = game_with_cps()
    manager = CsarManager()
    squadron = FakeSquadron()
    target = CsarTarget(pilot, squadron, Point(0, 0), 0, sea=False)
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
    target = CsarTarget(pilot, FakeSquadron(), Point(0, 0), 0, sea=False)
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
    target = CsarTarget(pilot, FakeSquadron(), Point(0, 0), 0, sea=False)
    pilot.mark_mia()
    manager.targets.append(target)

    manager.handle_pickup_results(game, {}, set())

    assert pilot.status is PilotStatus.MIA
    assert target in manager.targets


def test_csar_target_mission_types() -> None:
    target = CsarTarget(Pilot("Pilot"), FakeSquadron(), Point(0, 0), 0, sea=False)

    assert list(target.mission_types(for_player=True)) == [
        FlightType.CSAR,
        FlightType.TARCAP,
        FlightType.ESCORT,
        FlightType.SWEEP,
    ]

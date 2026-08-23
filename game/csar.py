from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Iterator

from dcs.mapping import Point

from game.sidc import (
    Entity,
    SidcDescribable,
    StandardIdentity,
    Status,
    SymbolSet,
)
from game.squadrons.pilot import Pilot, PilotStatus
from game.theater.missiontarget import MissionTarget
from game.utils import Distance, nautical_miles

if TYPE_CHECKING:
    from game import Game
    from game.ato.flighttype import FlightType
    from game.squadrons.squadron import Squadron
    from game.unitmap import FlyingUnit


CSAR_RECOVERY_RADIUS: Distance = nautical_miles(10)
CSAR_CAPTURE_RADIUS: Distance = nautical_miles(10)
CSAR_PICKUP_RADIUS_METERS = 300
CSAR_LAND_LIFETIME_TURNS = 8
CSAR_SEA_LIFETIME_TURNS = 1
CSAR_HELICOPTER_SURVIVAL_CHANCE = 0.20


class CsarResolution(Enum):
    RECOVERED = "recovered"
    CAPTURED = "captured"
    UNRESOLVED = "unresolved"


class CsarEntity(Entity):
    DOWNED_AIRCRAFT_PICKUP_POINT = 180300


@dataclass
class CsarTarget(MissionTarget, SidcDescribable):
    pilot: Pilot
    squadron: Squadron
    position: Point
    turn_created: int
    sea: bool
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    picked_up_by: str | None = None

    def __post_init__(self) -> None:
        MissionTarget.__init__(self, f"CSAR: {self.pilot.name}", self.position)

    @property
    def category(self) -> str:
        return "csar"

    @property
    def remaining_turns(self) -> int:
        # This is patched by CsarManager when displayed without a Game instance.
        return self.lifetime_turns

    @property
    def lifetime_turns(self) -> int:
        return CSAR_SEA_LIFETIME_TURNS if self.sea else CSAR_LAND_LIFETIME_TURNS

    @property
    def standard_identity(self) -> StandardIdentity:
        return StandardIdentity.FRIEND

    @property
    def sidc_status(self) -> Status:
        return Status.PRESENT

    @property
    def symbol_set_and_entity(self) -> tuple[SymbolSet, Entity]:
        return SymbolSet.CONTROL_MEASURE, CsarEntity.DOWNED_AIRCRAFT_PICKUP_POINT

    def is_friendly(self, to_player: bool) -> bool:
        return self.squadron.player == to_player

    def mission_types(self, for_player: bool) -> Iterator[FlightType]:
        from game.ato import FlightType

        if self.is_friendly(for_player):
            yield FlightType.CSAR
            yield FlightType.TARCAP
            yield FlightType.ESCORT
            yield FlightType.SWEEP


@dataclass
class CsarManager:
    targets: list[CsarTarget] = field(default_factory=list)

    def add_aircraft_survivor(
        self, game: Game, loss: FlyingUnit, position: Point
    ) -> CsarTarget | None:
        pilot = loss.pilot
        if pilot is None:
            return None
        if pilot.player and game.settings.invulnerable_player_pilots:
            return None
        return self._create_target(game, loss, position)

    def add_helicopter_loss(
        self, game: Game, loss: FlyingUnit, position: Point
    ) -> CsarTarget | None:
        if random.random() > CSAR_HELICOPTER_SURVIVAL_CHANCE:
            if loss.pilot is not None and (
                not loss.pilot.player or not game.settings.invulnerable_player_pilots
            ):
                loss.pilot.kill()
            return None
        return self.add_aircraft_survivor(game, loss, position)

    def _create_target(
        self, game: Game, loss: FlyingUnit, position: Point
    ) -> CsarTarget | None:
        pilot = loss.pilot
        if pilot is None:
            return None

        pilot.mark_mia()
        target = CsarTarget(
            pilot=pilot,
            squadron=loss.flight.squadron,
            position=position,
            turn_created=game.turn,
            sea=game.theater.is_in_sea(position),
        )
        resolution = self.resolve_by_control_points(game, target)
        if resolution is CsarResolution.RECOVERED:
            self.recover(game, target)
            return None
        if resolution is CsarResolution.CAPTURED:
            self.kill(game, target)
            return None
        self.targets.append(target)
        game.db.tgos.add(target.id, target)
        return target

    def recover(self, game: Game, target: CsarTarget) -> None:
        if target.pilot.status is PilotStatus.MIA:
            target.pilot.recover()
        if target.pilot not in target.squadron.available_pilots:
            target.squadron.available_pilots.append(target.pilot)
        self.remove(game, target)

    def kill(self, game: Game, target: CsarTarget) -> None:
        target.pilot.kill()
        self.remove(game, target)

    def remove(self, game: Game, target: CsarTarget) -> None:
        if target in self.targets:
            self.targets.remove(target)
        if target.id in game.db.tgos.objects:
            game.db.tgos.remove(target.id)

    def resolve_by_control_points(
        self, game: Game, target: CsarTarget
    ) -> CsarResolution:
        friendly: tuple[float, object] | None = None
        enemy: tuple[float, object] | None = None
        recovery_radius = nautical_miles(
            getattr(
                game.settings,
                "csar_friendly_recovery_radius",
                CSAR_RECOVERY_RADIUS.nautical_miles,
            )
        )
        capture_radius = nautical_miles(
            getattr(
                game.settings,
                "csar_enemy_capture_radius",
                CSAR_CAPTURE_RADIUS.nautical_miles,
            )
        )
        for cp in game.theater.controlpoints:
            distance = target.position.distance_to_point(cp.position)
            if cp.is_friendly(target.squadron.player):
                if distance <= recovery_radius.meters and (
                    friendly is None or distance < friendly[0]
                ):
                    friendly = (distance, cp)
            elif distance <= capture_radius.meters and (
                enemy is None or distance < enemy[0]
            ):
                enemy = (distance, cp)

        if friendly is None and enemy is None:
            return CsarResolution.UNRESOLVED
        if enemy is None:
            return CsarResolution.RECOVERED
        if friendly is None:
            return CsarResolution.CAPTURED
        return (
            CsarResolution.RECOVERED
            if friendly[0] <= enemy[0]
            else CsarResolution.CAPTURED
        )

    def process_turn(self, game: Game) -> None:
        for target in list(self.targets):
            resolution = self.resolve_by_control_points(game, target)
            if resolution is CsarResolution.RECOVERED:
                self.recover(game, target)
                continue
            if resolution is CsarResolution.CAPTURED:
                self.kill(game, target)
                continue
            if game.turn - target.turn_created >= target.lifetime_turns:
                self.kill(game, target)

    def handle_pickup_results(
        self, game: Game, picked_up: dict[uuid.UUID, str], killed_aircraft: set[str]
    ) -> None:
        for target in list(self.targets):
            rescuing_unit = picked_up.get(target.id)
            if rescuing_unit is None:
                continue
            if rescuing_unit in killed_aircraft:
                self.kill(game, target)
            else:
                self.recover(game, target)

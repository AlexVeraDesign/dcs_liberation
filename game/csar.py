from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterator

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


CSAR_RECOVERY_RADIUS: Distance = nautical_miles(20)
CSAR_CAPTURE_RADIUS: Distance = nautical_miles(20)
CSAR_GROUPING_RADIUS: Distance = nautical_miles(10)
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
class CsarSurvivor:
    pilot: Pilot
    squadron: Squadron
    aircraft: str | None = None
    position: Point | None = None
    ejection_turn: int | None = None
    ejection_time: datetime | None = None

    @property
    def squadron_name(self) -> str:
        return str(self.squadron)

    @property
    def base_name(self) -> str:
        return self.squadron.location.name


@dataclass
class CsarTarget(MissionTarget, SidcDescribable):
    pilot: Pilot
    squadron: Squadron
    position: Point
    turn_created: int
    sea: bool
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    picked_up_by: str | None = None
    survivors: list[CsarSurvivor] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._ensure_survivors()
        MissionTarget.__init__(self, self.display_name, self.position)

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._ensure_survivors()
        MissionTarget.__init__(self, self.display_name, self.position)

    def _ensure_survivors(self) -> None:
        if not hasattr(self, "survivors") or not self.survivors:
            self.survivors = [
                CsarSurvivor(
                    self.pilot,
                    self.squadron,
                    position=self.position,
                    ejection_turn=self.turn_created,
                )
            ]
        if not hasattr(self, "picked_up_by"):
            self.picked_up_by = None

    @property
    def display_name(self) -> str:
        count = len(self.survivors)
        if count == 1:
            return f"CSAR: {self.survivors[0].pilot.name}"
        return f"CSAR: {count} pilots"

    def refresh_name(self) -> None:
        self.name = self.display_name

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

    def turns_remaining(self, current_turn: int) -> int:
        return max(0, self.lifetime_turns - (current_turn - self.turn_created))

    @property
    def location_text(self) -> str:
        latlng = self.position.latlng()
        return f"{latlng.lat:.4f}, {latlng.lng:.4f}"

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
        if not loss.flight.squadron.player:
            pilot.kill()
            return None
        if pilot.player and game.settings.invulnerable_player_pilots:
            return None
        return self._create_target(game, loss, position)

    def add_helicopter_loss(
        self, game: Game, loss: FlyingUnit, position: Point
    ) -> CsarTarget | None:
        if loss.pilot is not None and not loss.flight.squadron.player:
            loss.pilot.kill()
            return None
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
        survivor = CsarSurvivor(
            pilot=pilot,
            squadron=loss.flight.squadron,
            aircraft=str(loss.flight.unit_type),
            position=position,
            ejection_turn=game.turn,
            ejection_time=game.simulation_time,
        )
        target = CsarTarget(
            pilot=pilot,
            squadron=loss.flight.squadron,
            position=position,
            turn_created=game.turn,
            sea=game.theater.is_in_sea(position),
            survivors=[survivor],
        )
        resolution = self.resolve_by_control_points(game, target)
        if resolution is CsarResolution.RECOVERED:
            self.recover(game, target)
            return None
        if resolution is CsarResolution.CAPTURED:
            self.kill(game, target)
            return None
        return self.add_or_group_target(game, target)

    def add_or_group_target(self, game: Game, target: CsarTarget) -> CsarTarget:
        group = self.connected_targets_for(game, target)
        if not group:
            self.targets.append(target)
            game.db.tgos.add(target.id, target)
            return target

        primary = group[0]
        for grouped_target in group[1:]:
            primary.survivors.extend(grouped_target.survivors)
            self.remove(game, grouped_target)
        primary.survivors.extend(target.survivors)
        ejection_turns = [
            survivor.ejection_turn
            for survivor in primary.survivors
            if survivor.ejection_turn is not None
        ]
        if ejection_turns:
            primary.turn_created = min(ejection_turns)
        primary.sea = all(
            game.theater.is_in_sea(s.position or primary.position)
            for s in primary.survivors
        )
        primary.position = self.center_point(game, primary.survivors)
        primary.refresh_name()
        if primary.id not in game.db.tgos.objects:
            game.db.tgos.add(primary.id, primary)
        return primary

    def connected_targets_for(self, game: Game, target: CsarTarget) -> list[CsarTarget]:
        radius = nautical_miles(
            getattr(
                game.settings,
                "csar_grouping_radius",
                CSAR_GROUPING_RADIUS.nautical_miles,
            )
        )
        if radius.meters <= 0:
            return []

        connected: list[CsarTarget] = []
        queue = [target]
        candidates = [t for t in self.targets if t.is_friendly(target.squadron.player)]
        while queue:
            current = queue.pop()
            current_positions = self.survivor_positions(current)
            for candidate in list(candidates):
                if candidate in connected:
                    continue
                if self.targets_within_radius(current_positions, candidate, radius):
                    connected.append(candidate)
                    queue.append(candidate)
                    candidates.remove(candidate)
        return connected

    @staticmethod
    def survivor_positions(target: CsarTarget) -> list[Point]:
        return [s.position or target.position for s in target.survivors]

    def targets_within_radius(
        self, positions: list[Point], candidate: CsarTarget, radius: Distance
    ) -> bool:
        for position in positions:
            for candidate_position in self.survivor_positions(candidate):
                if position.distance_to_point(candidate_position) <= radius.meters:
                    return True
        return False

    @staticmethod
    def center_point(game: Game, survivors: list[CsarSurvivor]) -> Point:
        positions = [s.position for s in survivors if s.position is not None]
        if not positions:
            raise RuntimeError("Cannot center CSAR target without survivor positions")
        return game.point_in_world(
            sum(position.x for position in positions) / len(positions),
            sum(position.y for position in positions) / len(positions),
        )

    def recover(self, game: Game, target: CsarTarget) -> None:
        for survivor in target.survivors:
            if survivor.pilot.status is PilotStatus.MIA:
                survivor.pilot.recover()
            if survivor.pilot not in survivor.squadron.available_pilots:
                survivor.squadron.available_pilots.append(survivor.pilot)
        self.remove(game, target)

    def kill(self, game: Game, target: CsarTarget) -> None:
        for survivor in target.survivors:
            survivor.pilot.kill()
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

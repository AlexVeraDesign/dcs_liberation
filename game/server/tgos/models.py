from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

from game.server.leaflet import LeafletPoint

if TYPE_CHECKING:
    from game import Game
    from game.csar import CsarTarget
    from game.theater import MissionTarget, TheaterGroundObject


class TgoJs(BaseModel):
    id: UUID
    name: str
    control_point_name: str
    category: str
    blue: bool
    position: LeafletPoint
    units: list[str]  # TODO: Event stream
    threat_ranges: list[float]  # TODO: Event stream
    detection_ranges: list[float]  # TODO: Event stream
    dead: bool  # TODO: Event stream
    sidc: str  # TODO: Event stream

    class Config:
        title = "Tgo"

    @staticmethod
    def for_tgo(tgo: TheaterGroundObject | CsarTarget) -> TgoJs:
        from game.csar import CsarTarget

        if isinstance(tgo, CsarTarget):
            tgo._ensure_survivors()
            tgo.refresh_name()
            squadrons = sorted({survivor.squadron_name for survivor in tgo.survivors})
            return TgoJs(
                id=tgo.id,
                name=tgo.name,
                control_point_name=", ".join(squadrons),
                category=tgo.category,
                blue=tgo.squadron.player,
                position=LeafletPoint.from_pydcs(tgo.position),
                units=(
                    [s.pilot.name for s in tgo.survivors]
                    if len(tgo.survivors) > 1
                    else []
                ),
                threat_ranges=[],
                detection_ranges=[],
                dead=False,
                sidc=str(tgo.sidc()),
            )

        threat_ranges = [group.max_threat_range().meters for group in tgo.groups]
        detection_ranges = [group.max_detection_range().meters for group in tgo.groups]
        return TgoJs(
            id=tgo.id,
            name=tgo.name,
            control_point_name=tgo.control_point.name,
            category=tgo.category,
            blue=tgo.control_point.captured,
            position=LeafletPoint.from_pydcs(tgo.position),
            units=[unit.display_name for unit in tgo.units],
            threat_ranges=threat_ranges,
            detection_ranges=detection_ranges,
            dead=tgo.is_dead,
            sidc=str(tgo.sidc()),
        )

    @staticmethod
    def all_in_game(game: Game) -> list[TgoJs]:
        tgos = []
        for control_point in game.theater.controlpoints:
            for tgo in control_point.connected_objectives:
                if not tgo.is_control_point:
                    tgos.append(TgoJs.for_tgo(tgo))
        for csar_target in game.csar.targets:
            tgos.append(TgoJs.for_tgo(csar_target))
        return tgos

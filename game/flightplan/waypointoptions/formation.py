from __future__ import annotations

from collections.abc import Iterator
from enum import Enum
from typing import Any

from dcs.task import OptFormation, Task

from game.flightplan.waypointactions.taskcontext import TaskContext
from game.flightplan.waypointoptions.waypointoption import WaypointOption


class Formation(WaypointOption, Enum):
    FINGER_FOUR_CLOSE = OptFormation.finger_four_close()
    FINGER_FOUR_OPEN = OptFormation.finger_four_open()
    LINE_ABREAST_OPEN = OptFormation.line_abreast_open()
    SPREAD_FOUR_OPEN = OptFormation.spread_four_open()
    TRAIL_OPEN = OptFormation.trail_open()

    @classmethod
    def _missing_(cls, value: object) -> Formation | None:
        def option_params(data: Any) -> dict[str, Any]:
            if not isinstance(data, dict):
                data = data.__dict__
            action = data.get("params", {}).get("action", {})
            if not isinstance(action, dict):
                action = action.__dict__
            return action.get("params", {})

        try:
            params = option_params(value)
        except AttributeError:
            return None

        for formation in cls:
            formation_params = option_params(formation.value)
            if (
                params.get("name") == formation_params.get("name")
                and params.get("value") == formation_params.get("value")
                and params.get("formationIndex")
                == formation_params.get("formationIndex")
                and params.get("variantIndex") == formation_params.get("variantIndex")
            ):
                return formation
        return None

    def id(self) -> str:
        return "formation"

    def iter_tasks(self, ctx: TaskContext) -> Iterator[Task]:
        yield self.value

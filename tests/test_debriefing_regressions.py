from types import SimpleNamespace

from dcs.task import OptFormation

from game.debriefing import FlyingUnitHitPointUpdate
from game.flightplan.waypointoptions.formation import Formation


def test_flying_unit_hit_point_update_can_be_counted_dead() -> None:
    unit = SimpleNamespace(flight=SimpleNamespace(departure=SimpleNamespace(captured=True)))

    update = FlyingUnitHitPointUpdate(unit, 1)

    assert update.is_dead()


def test_formation_loads_from_legacy_task_dict() -> None:
    legacy_value = {
        "id": "WrappedAction",
        "auto": False,
        "enabled": True,
        "params": {
            "action": {
                "id": "Option",
                "params": {
                    "name": 5,
                    "value": 65538,
                    "formationIndex": 1,
                    "variantIndex": 2,
                },
            }
        },
        "number": 1,
    }

    assert Formation(legacy_value) is Formation.LINE_ABREAST_OPEN


def test_formation_loads_from_legacy_task_dict_with_different_task_number() -> None:
    legacy_value = {
        "id": "WrappedAction",
        "auto": False,
        "enabled": True,
        "params": {
            "action": {
                "id": "Option",
                "params": {
                    "name": 5,
                    "value": 65538,
                    "formationIndex": 1,
                    "variantIndex": 2,
                },
            }
        },
        "number": 2,
    }

    assert Formation(legacy_value) is Formation.LINE_ABREAST_OPEN


def test_formation_loads_from_legacy_task_object_with_different_task_number() -> None:
    legacy_value = OptFormation.line_abreast_open()
    legacy_value.number = 2

    assert Formation(legacy_value) is Formation.LINE_ABREAST_OPEN

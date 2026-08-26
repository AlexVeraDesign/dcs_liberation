from uuid import UUID

from typing import cast

from dcs import Point
from dcs.mapping import LatLng
from fastapi import APIRouter, Body, Depends, HTTPException, status
from starlette.responses import Response

from game import Game
from game.csar import CsarTarget
from game.theater import TheaterGroundObject
from .models import TgoJs
from ..dependencies import GameContext
from ..leaflet import LeafletPoint

router: APIRouter = APIRouter(prefix="/tgos")


@router.get("/", operation_id="list_tgos", response_model=list[TgoJs])
def list_tgos(game: Game = Depends(GameContext.require)) -> list[TgoJs]:
    return TgoJs.all_in_game(game)


@router.get("/{tgo_id}", operation_id="get_tgo_by_id", response_model=TgoJs)
def get_tgo(tgo_id: UUID, game: Game = Depends(GameContext.require)) -> TgoJs:
    return TgoJs.for_tgo(
        cast(TheaterGroundObject | CsarTarget, game.db.tgos.get(tgo_id))
    )


def csar_target(tgo_id: UUID, game: Game) -> CsarTarget:
    target = game.db.tgos.get(tgo_id)
    if not isinstance(target, CsarTarget):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"{target} is not a CSAR target",
        )
    if not target.is_friendly(to_player=True):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"{target} is not owned by the player",
        )
    return target


@router.get(
    "/{tgo_id}/destination-in-range",
    operation_id="tgo_destination_in_range",
    response_model=bool,
)
def destination_in_range(
    tgo_id: UUID, lat: float, lng: float, game: Game = Depends(GameContext.require)
) -> bool:
    target = csar_target(tgo_id, game)
    point = Point.from_latlng(LatLng(lat, lng), game.theater.terrain)
    return target.can_plan_movement and target.destination_in_range(point)


@router.put(
    "/{tgo_id}/destination",
    operation_id="set_tgo_destination",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def set_destination(
    tgo_id: UUID,
    destination: LeafletPoint = Body(..., title="destination"),
    game: Game = Depends(GameContext.require),
) -> None:
    target = csar_target(tgo_id, game)
    if not target.can_plan_movement:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"{target} is not mobile")

    point = Point.from_latlng(
        LatLng(destination.lat, destination.lng), game.theater.terrain
    )
    try:
        target.plan_movement(point)
    except ValueError as ex:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(ex)) from ex

    from .. import EventStream

    with EventStream.event_context() as events:
        events.update_tgo(target)


@router.put(
    "/{tgo_id}/cancel-travel",
    operation_id="clear_tgo_destination",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def cancel_travel(tgo_id: UUID, game: Game = Depends(GameContext.require)) -> None:
    target = csar_target(tgo_id, game)
    if not target.can_plan_movement:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"{target} is not mobile")

    target.clear_planned_movement()

    from .. import EventStream

    with EventStream.event_context() as events:
        events.update_tgo(target)

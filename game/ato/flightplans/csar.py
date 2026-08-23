from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, TYPE_CHECKING, Type

from game.ato.flightplans.standard import StandardFlightPlan, StandardLayout
from game.csar import CSAR_PICKUP_RADIUS_METERS
from game.utils import Distance, meters
from .ibuilder import IBuilder
from .planningerror import PlanningError
from .uizonedisplay import UiZone, UiZoneDisplay
from .waypointbuilder import WaypointBuilder
from ..flightwaypoint import FlightWaypointType

if TYPE_CHECKING:
    from ..flightwaypoint import FlightWaypoint


@dataclass(frozen=True)
class CsarLayout(StandardLayout):
    nav_to_pickup: list[FlightWaypoint]
    ingress: FlightWaypoint
    pickup: FlightWaypoint
    nav_to_home: list[FlightWaypoint]

    def iter_waypoints(self) -> Iterator[FlightWaypoint]:
        yield self.departure
        yield from self.nav_to_pickup
        yield self.ingress
        yield self.pickup
        yield from self.nav_to_home
        yield self.arrival
        if self.divert is not None:
            yield self.divert
        yield self.bullseye


class CsarFlightPlan(StandardFlightPlan[CsarLayout], UiZoneDisplay):
    @staticmethod
    def builder_type() -> Type[Builder]:
        return Builder

    @property
    def tot_waypoint(self) -> FlightWaypoint:
        return self.layout.pickup

    def tot_for_waypoint(self, waypoint: FlightWaypoint) -> datetime | None:
        if waypoint == self.tot_waypoint:
            return self.tot
        return None

    def depart_time_for_waypoint(self, waypoint: FlightWaypoint) -> datetime | None:
        return None

    @property
    def pickup_zone_radius(self) -> Distance:
        return meters(
            getattr(
                self.flight.coalition.game.settings,
                "csar_pickup_radius",
                CSAR_PICKUP_RADIUS_METERS,
            )
        )

    @property
    def mission_begin_on_station_time(self) -> datetime | None:
        return None

    @property
    def mission_departure_time(self) -> datetime:
        return self.package.time_over_target

    def ui_zone(self) -> UiZone:
        return UiZone([self.layout.pickup.position], self.pickup_zone_radius)


class Builder(IBuilder[CsarFlightPlan, CsarLayout]):
    def layout(self) -> CsarLayout:
        if not self.flight.is_helo or self.flight.squadron.aircraft.cabin_size <= 0:
            raise PlanningError("CSAR requires a transport-capable helicopter")
        assert self.package.waypoints is not None

        altitude = self.doctrine.helicopter.air_assault_nav_altitude
        builder = WaypointBuilder(self.flight, self.coalition)
        pickup = builder.csar_pickup_zone(self.package.target)

        return CsarLayout(
            departure=builder.takeoff(self.flight.departure),
            nav_to_pickup=builder.nav_path(
                self.flight.departure.position,
                self.package.waypoints.ingress,
                altitude,
                altitude_is_agl=True,
            ),
            ingress=builder.ingress(
                FlightWaypointType.INGRESS_AIR_ASSAULT,
                self.package.waypoints.ingress,
                self.package.target,
            ),
            pickup=pickup,
            nav_to_home=builder.nav_path(
                pickup.position,
                self.flight.arrival.position,
                altitude,
                altitude_is_agl=True,
            ),
            arrival=builder.land(self.flight.arrival),
            divert=builder.divert(self.flight.divert),
            bullseye=builder.bullseye(),
        )

    def build(self, dump_debug_info: bool = False) -> CsarFlightPlan:
        return CsarFlightPlan(self.flight, self.layout())

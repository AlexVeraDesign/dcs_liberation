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
    from dcs.mapping import Point

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
    @staticmethod
    def _profiled_nav_path(
        builder: WaypointBuilder,
        origin: Point,
        destination: Point,
        altitude: Distance,
    ) -> list[FlightWaypoint]:
        if origin.distance_to_point(destination) == 0:
            return []

        nav_path = builder.nav_path(
            origin,
            destination,
            altitude,
            altitude_is_agl=True,
        )
        toc_target = nav_path[0].position if nav_path else destination
        tod_origin = nav_path[-1].position if nav_path else origin

        return [
            builder.ascend_point(origin.lerp(toc_target, 0.25), altitude, True),
            *nav_path,
            builder.descent_point(tod_origin.lerp(destination, 0.75), altitude, True),
        ]

    def layout(self) -> CsarLayout:
        if not self.flight.is_helo or self.flight.squadron.aircraft.cabin_size <= 0:
            raise PlanningError("CSAR requires a transport-capable helicopter")

        altitude = self.doctrine.resolve_air_assault_nav_altitude()
        builder = WaypointBuilder(self.flight, self.coalition)
        pickup = builder.csar_pickup_zone(self.package.target)
        ingress_position = self.ingress_position()

        return CsarLayout(
            departure=builder.takeoff(self.flight.departure),
            nav_to_pickup=self._profiled_nav_path(
                builder,
                self.flight.departure.position,
                ingress_position,
                altitude,
            ),
            ingress=builder.ingress(
                FlightWaypointType.INGRESS_AIR_ASSAULT,
                ingress_position,
                self.package.target,
            ),
            pickup=pickup,
            nav_to_home=self._profiled_nav_path(
                builder,
                pickup.position,
                self.flight.arrival.position,
                altitude,
            ),
            arrival=builder.land(self.flight.arrival),
            divert=builder.divert(self.flight.divert),
            bullseye=builder.bullseye(),
        )

    def ingress_position(self) -> Point:
        if self.package.waypoints is not None:
            return self.package.waypoints.ingress

        target = self.package.target.position
        heading_to_departure = target.heading_between_point(
            self.flight.departure.position
        )
        return target.point_from_heading(heading_to_departure, 2000)

    def build(self, dump_debug_info: bool = False) -> CsarFlightPlan:
        return CsarFlightPlan(self.flight, self.layout())

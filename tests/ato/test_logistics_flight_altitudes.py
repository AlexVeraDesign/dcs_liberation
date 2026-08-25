from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from dcs import Point
from dcs.terrain import Caucasus

from game.ato.flightplans.airassault import Builder as AirAssaultBuilder
from game.ato.flightplans.airlift import Builder as AirliftBuilder
from game.ato.flightplans.ferry import Builder as FerryBuilder
from game.ato.flightplans.waypointbuilder import WaypointBuilder
from game.ato.flightwaypoint import AltitudeReference, FlightWaypoint
from game.ato.flightwaypointtype import FlightWaypointType
from game.data.doctrine import (
    Aewc,
    Cap,
    Cas,
    Doctrine,
    GroundUnitProcurementRatios,
    Helicopter,
    Sweep,
    Tactics,
)
from game.data.units import UnitClass
from game.theater.controlpoint import ControlPointType
from game.theater.missiontarget import MissionTarget
from game.utils import Distance, feet, meters, nautical_miles


def point(x: float, y: float) -> Point:
    return Point(x, y, Caucasus())


def doctrine(air_assault_nav_altitude: Distance = feet(1500)) -> Doctrine:
    return Doctrine(
        name="test",
        hold_distance=nautical_miles(10),
        push_distance=nautical_miles(10),
        join_distance=nautical_miles(10),
        max_ingress_distance=nautical_miles(50),
        min_ingress_distance=nautical_miles(5),
        combat_altitude=feet(20000),
        rendezvous_altitude=feet(15000),
        ground_unit_procurement_ratios=GroundUnitProcurementRatios(
            {UnitClass.TANK: 1.0}
        ),
        helicopter=Helicopter(
            combat_altitude=feet(1500),
            rendezvous_altitude=feet(1000),
            air_assault_nav_altitude=air_assault_nav_altitude,
        ),
        aewc=Aewc(duration=datetime.min - datetime.min),
        cas=Cas(duration=datetime.min - datetime.min),
        cap=Cap(
            duration=datetime.min - datetime.min,
            min_track_length=nautical_miles(20),
            max_track_length=nautical_miles(40),
            min_distance_from_cp=nautical_miles(10),
            max_distance_from_cp=nautical_miles(20),
            engagement_range=nautical_miles(40),
            min_patrol_altitude=feet(15000),
            max_patrol_altitude=feet(30000),
        ),
        sweep=Sweep(distance=nautical_miles(30)),
        tactics=Tactics(
            air_to_air_missile_attack_range=None,
            air_defence_evades_anti_radiation_missiles=False,
        ),
    )


class ThreatZones:
    def path_threatened(self, a: Point, b: Point) -> bool:
        return False


class NavMesh:
    def shortest_path(self, a: Point, b: Point) -> list[Point]:
        return [a, a.lerp(b, 0.5), b]


def control_point(name: str, position: Point) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        position=position,
        theater=SimpleNamespace(),
        cptype=ControlPointType.AIRBASE,
        is_fleet=False,
    )


def flight(
    *,
    is_helo: bool,
    preferred_patrol_altitude: Distance = feet(24000),
    air_assault_nav_altitude: Distance = feet(1500),
) -> SimpleNamespace:
    departure = control_point("Departure", point(0, 0))
    arrival = control_point("Arrival", point(30000, 0))
    unit_type = SimpleNamespace(
        dcs_unit_type=SimpleNamespace(helicopter=is_helo),
        preferred_patrol_altitude=preferred_patrol_altitude,
    )
    coalition = SimpleNamespace(
        doctrine=doctrine(air_assault_nav_altitude),
        opponent=SimpleNamespace(threat_zone=ThreatZones()),
        nav_mesh=NavMesh(),
        bullseye=SimpleNamespace(position=point(5000, 5000)),
        player=True,
    )
    return SimpleNamespace(
        cargo=None,
        departure=departure,
        arrival=arrival,
        divert=None,
        is_helo=is_helo,
        unit_type=unit_type,
        coalition=coalition,
        package=SimpleNamespace(
            time_over_target=datetime(2026, 1, 1),
            waypoints=SimpleNamespace(ingress=point(20000, 0)),
            target=MissionTarget("Target", point(25000, 0)),
        ),
    )


def patch_nav_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def nav_path(
        self: WaypointBuilder,
        a: Point,
        b: Point,
        altitude: Distance,
        altitude_is_agl: bool = False,
    ) -> list[FlightWaypoint]:
        return [WaypointBuilder.nav(a.lerp(b, 0.5), altitude, altitude_is_agl)]

    monkeypatch.setattr(WaypointBuilder, "nav_path", nav_path)


def assert_waypoints(
    waypoints: list[FlightWaypoint],
    expected_types: list[FlightWaypointType],
    expected_altitude: Distance,
    expected_alt_type: AltitudeReference,
) -> None:
    assert [w.waypoint_type for w in waypoints] == expected_types
    for waypoint in waypoints:
        assert waypoint.alt.feet == pytest.approx(expected_altitude.feet)
        assert waypoint.alt_type == expected_alt_type


def test_ferry_helicopter_nav_uses_3000_ft_agl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_nav_path(monkeypatch)

    layout = FerryBuilder(cast(Any, flight(is_helo=True))).layout()

    assert_waypoints(
        layout.nav_to_destination,
        [FlightWaypointType.NAV],
        feet(3000),
        "RADIO",
    )


def test_ferry_fixed_wing_nav_keeps_preferred_patrol_altitude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_nav_path(monkeypatch)
    preferred_altitude = feet(22000)

    layout = FerryBuilder(
        cast(Any, flight(is_helo=False, preferred_patrol_altitude=preferred_altitude))
    ).layout()

    assert_waypoints(
        layout.nav_to_destination,
        [FlightWaypointType.NAV],
        preferred_altitude,
        "BARO",
    )


def test_airlift_helicopter_cruise_profile_uses_3000_ft_agl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_nav_path(monkeypatch)
    helo_flight = flight(is_helo=True)
    helo_flight.cargo = SimpleNamespace(
        origin=control_point("Pickup", point(10000, 0)),
        next_stop=control_point("Dropoff", point(20000, 0)),
    )

    layout = AirliftBuilder(cast(Any, helo_flight)).layout()

    for segment in (
        layout.nav_to_pickup,
        layout.nav_to_drop_off,
        layout.nav_to_home,
    ):
        assert_waypoints(
            segment,
            [
                FlightWaypointType.ASCEND_POINT,
                FlightWaypointType.NAV,
                FlightWaypointType.DESCENT_POINT,
            ],
            feet(3000),
            "RADIO",
        )


def test_airlift_fixed_wing_cruise_profile_uses_preferred_patrol_altitude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_nav_path(monkeypatch)
    preferred_altitude = feet(18000)
    transport_flight = flight(
        is_helo=False, preferred_patrol_altitude=preferred_altitude
    )
    transport_flight.cargo = SimpleNamespace(
        origin=control_point("Pickup", point(10000, 0)),
        next_stop=control_point("Dropoff", point(20000, 0)),
    )

    layout = AirliftBuilder(cast(Any, transport_flight)).layout()

    for segment in (
        layout.nav_to_pickup,
        layout.nav_to_drop_off,
        layout.nav_to_home,
    ):
        assert_waypoints(
            segment,
            [
                FlightWaypointType.ASCEND_POINT,
                FlightWaypointType.NAV,
                FlightWaypointType.DESCENT_POINT,
            ],
            preferred_altitude,
            "BARO",
        )


def test_air_assault_nav_uses_3000_ft_agl_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_nav_path(monkeypatch)

    layout = AirAssaultBuilder(cast(Any, flight(is_helo=True))).layout()

    assert layout.pickup is not None
    assert layout.drop_off.waypoint_type == FlightWaypointType.DROPOFF_ZONE
    assert layout.target.only_for_player
    for segment in (layout.nav_to_ingress, layout.nav_to_home):
        assert_waypoints(segment, [FlightWaypointType.NAV], feet(3000), "RADIO")


def test_air_assault_nav_respects_higher_doctrine_altitude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_nav_path(monkeypatch)

    layout = AirAssaultBuilder(
        cast(Any, flight(is_helo=True, air_assault_nav_altitude=feet(4500)))
    ).layout()

    for segment in (layout.nav_to_ingress, layout.nav_to_home):
        assert_waypoints(segment, [FlightWaypointType.NAV], feet(4500), "RADIO")

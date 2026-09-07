"""What a fuel invoice charges for depends entirely on these two functions.

The reimbursement is distance / efficiency * petrol rate, so every defect in
the distance becomes money paid out. Four were found:

  1. an address the city table did not recognise resolved to Lahore's centre,
     turning local Karachi jobs into ~1,000km legs;
  2. addresses within one city were separated by an offset derived from the
     address's *character count*, so the distance between two sites was a
     property of their spelling;
  3. a distance under 0.1km was replaced with `8.5 + trip_number * 1.5`,
     inventing kilometres outright;
  4. the straight-line distance was reimbursed as though it were the road.

These tests hold each of those shut.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.services.technician_service import (
    PRECISION_CITY, PRECISION_GPS, PRECISION_NONE, ROAD_DISTANCE_FACTOR,
    calculate_distance_km, resolve_coordinates, road_distance_km)

KARACHI = (24.8607, 67.0011, PRECISION_CITY)
LAHORE = (31.5204, 74.3587, PRECISION_CITY)


@pytest.fixture
def app_context():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_an_unrecognised_address_resolves_to_nothing(app_context):
    """It used to resolve to Lahore, which is how a technician who never left
    Karachi was paid for a thousand kilometres."""
    lat, lng, precision = resolve_coordinates('Plot 42, Some Lane')

    assert precision is PRECISION_NONE
    assert (lat, lng) == (None, None)


def test_a_named_city_resolves_to_that_city(app_context):
    lat, lng, precision = resolve_coordinates('USMANIA COLONY MANGOPIR ROAD KARACHI')

    assert precision == PRECISION_CITY
    assert (round(lat, 4), round(lng, 4)) == (24.8607, 67.0011)


def test_two_addresses_in_one_city_are_not_spread_by_their_spelling(app_context):
    """The old offset was `(len(address) % 10) * 0.005`, so the distance
    between two sites depended on how many characters their names had."""
    short = resolve_coordinates('DHA KARACHI')
    long = resolve_coordinates('USMANIA COLONY MANGOPIR ROAD KARACHI, NEAR THE DEPOT')

    assert short[:2] == long[:2]


def test_distance_within_one_city_is_unknown_rather_than_invented(app_context):
    """Both ends known only as "somewhere in Karachi" carries no distance.
    Returning a number here is guessing with someone's money."""
    assert road_distance_km(KARACHI, KARACHI) is None


def test_distance_is_unknown_when_either_end_is_unresolved(app_context):
    nowhere = (None, None, PRECISION_NONE)

    assert road_distance_km(KARACHI, nowhere) is None
    assert road_distance_km(nowhere, LAHORE) is None


def test_intercity_distance_is_the_road_not_the_straight_line(app_context):
    straight = calculate_distance_km(*KARACHI[:2], *LAHORE[:2])
    road = road_distance_km(KARACHI, LAHORE)

    assert road is not None
    assert road > straight, 'a rider on a road covers more than the great circle'
    assert road == pytest.approx(straight * ROAD_DISTANCE_FACTOR, rel=0.01)
    # Karachi to Lahore is roughly 1,200km by road.
    assert 1100 < road < 1500


def test_gps_endpoints_give_a_short_urban_distance(app_context):
    """Two real fixes a few km apart stay a few km apart - the road factor
    scales them, it does not replace them."""
    depot = (24.8607, 67.0011, PRECISION_GPS)
    site = (24.9200, 67.0800, PRECISION_GPS)

    road = road_distance_km(depot, site)
    assert road is not None
    assert 8 < road < 20, f'{road}km is not a plausible cross-town hop'


def test_no_distance_is_ever_synthesised_from_the_trip_number(app_context):
    """`8.5 + idx * 1.5` produced 10.0, 11.5, 13.0 ... for coincident points.
    Nothing may return those any more."""
    for _trip_number in range(1, 6):
        assert road_distance_km(KARACHI, KARACHI) is None

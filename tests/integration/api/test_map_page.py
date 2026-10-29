"""T024: the map page renders with its form, a pinned Leaflet and the API path."""


def test_map_page(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert '<form id="plan-form"' in html
    assert 'name="start"' in html and 'name="finish"' in html
    for field in (
        "start_fuel_gallons",
        "corridor_miles",
        "reserve_gallons",
        "min_saving_per_stop_usd",
    ):
        assert f'name="{field}"' in html
    assert "cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js" in html
    assert 'integrity="sha512-' in html
    assert "/api/v1/route-plan/" in html
    assert "tile.openstreetmap.org" in html
    assert "{{" not in html and "{%" not in html


def test_tiles_are_requested_with_a_referrer(client):
    # Django sends Referrer-Policy: same-origin, so without this the browser sends no Referer
    # to tile.openstreetmap.org and OSM answers every tile with "403 Access blocked".
    html = client.get("/").content.decode()
    assert 'referrerPolicy: "strict-origin-when-cross-origin"' in html


def test_page_defaults_to_the_api_minimum_saving_and_shows_the_cheapest_cost(client):
    html = client.get("/").content.decode()
    field = 'name="min_saving_per_stop_usd" type="number" min="0" max="100" step="any" value="5"'
    assert field in html
    assert "minimum_possible_cost_usd" in html
    assert "cheapest possible" in html

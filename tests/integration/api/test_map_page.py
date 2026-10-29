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

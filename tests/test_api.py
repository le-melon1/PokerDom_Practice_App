from backend.api import app


def test_reset_table_route_exists():
    routes = {route.path for route in app.routes}
    assert "/api/table/reset" in routes

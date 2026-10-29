from django.views.generic import TemplateView


class MapView(TemplateView):
    """The map page: a form that calls the route-plan API and draws the result."""

    template_name = "web/map.html"

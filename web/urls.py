from django.urls import path

from web.views import MapView

urlpatterns = [
    path("", MapView.as_view(), name="map"),
]

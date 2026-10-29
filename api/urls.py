from django.urls import path

from api.views import RoutePlanView

urlpatterns = [
    path("api/v1/route-plan/", RoutePlanView.as_view(), name="route-plan"),
]

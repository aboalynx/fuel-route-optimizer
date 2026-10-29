from django.contrib import admin

from .models import FuelPrice, FuelStation


class ReadOnlyAdmin(admin.ModelAdmin):
    """Station data is rebuilt by build_station_data, never edited by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FuelStation)
class FuelStationAdmin(ReadOnlyAdmin):
    list_display = ("opis_id", "name", "city", "state", "best_price", "geo_source")
    search_fields = ("name", "city")


@admin.register(FuelPrice)
class FuelPriceAdmin(ReadOnlyAdmin):
    list_display = ("id", "station", "rack_id", "raw_name", "price")
    search_fields = ("raw_name",)

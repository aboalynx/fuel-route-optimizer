from django.db import models

from .fuel_station import FuelStation

# No Meta.ordering: dumpdata then orders by primary key (ids are assigned
# explicitly by build_station_data), which keeps the fixture byte-stable.


class FuelPrice(models.Model):
    """One raw US row of the price file, kept for traceability."""

    station = models.ForeignKey(FuelStation, related_name="prices", on_delete=models.CASCADE)
    rack_id = models.IntegerField()
    raw_name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=8)

    def __str__(self):
        return f"{self.station_id} rack {self.rack_id}: {self.price}"

from django.db import models

from stations.enums import GeoSource

# No Meta.ordering: dumpdata then orders by primary key, which keeps the
# shipped fixture byte-stable between rebuilds.


class FuelStation(models.Model):
    """One located US truck stop, keyed by its OPIS Truckstop ID."""

    opis_id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2, db_index=True)
    lat = models.FloatField(null=True)
    lng = models.FloatField(null=True)
    geo_source = models.CharField(max_length=20, choices=GeoSource.choices())
    match_score = models.PositiveSmallIntegerField(null=True)
    # Minimum of the station's price rows; exact, the CSV has up to 8 decimals.
    best_price = models.DecimalField(max_digits=12, decimal_places=8)

    def __str__(self):
        return f"{self.opis_id} {self.name} ({self.city}, {self.state})"

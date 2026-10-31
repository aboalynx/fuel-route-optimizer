"""Load the place lookup once per process (at server start via api/services/warmup.py, else on first
use; never in AppConfig.ready()).

Tests reset it with get_place_index.cache_clear().
"""

from functools import lru_cache
from pathlib import Path

from django.conf import settings

from planner.locations import PlaceIndex, load_place_index


@lru_cache(maxsize=1)
def get_place_index() -> PlaceIndex:
    """The place index; raises PlaceDataMissing (not cached) when the file is unusable."""
    path = Path(settings.PLACES_INDEX_FILE)
    return load_place_index(path, label=_label(path))


def _label(path: Path) -> str:
    """The path as shown in messages: relative to the project when it is inside it."""
    try:
        return path.resolve().relative_to(Path(settings.BASE_DIR).resolve()).as_posix()
    except ValueError:
        return str(path)

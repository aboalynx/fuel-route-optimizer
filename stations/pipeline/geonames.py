"""Offline gazetteer: GeoNames US populated places (pure, no Django).

US.txt is tab-separated with no header and no quoting, so it is split by hand rather than
read with the csv module (names may contain '"').
"""

from dataclasses import dataclass, field
from pathlib import Path

from stations.enums import MatchVia

GAZETTEER_URL = "https://download.geonames.org/export/dump/US.zip"

# Feature codes of class P that are not places today: historical, abandoned, destroyed.
EXCLUDED_FEATURE_CODES = frozenset({"PPLH", "PPLQ", "PPLW"})

_TOKEN_MAP = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}

# US.txt column positions.
_ID, _NAME, _ASCII, _ALT, _LAT, _LNG, _CLASS, _CODE, _STATE, _POP = 0, 1, 2, 3, 4, 5, 6, 7, 10, 14

Key = tuple[str, str]  # (normalised name, state)


class GazetteerMissing(FileNotFoundError):
    def __init__(self, path: Path):
        super().__init__(
            f"GeoNames file not found: {path}. Download {GAZETTEER_URL}, "
            f"unzip it and place US.txt at that path."
        )


@dataclass(frozen=True)
class Place:
    geonameid: int
    name: str
    state: str
    lat_text: str
    lng_text: str
    population: int


@dataclass
class Gazetteer:
    primary: dict[Key, Place] = field(default_factory=dict)
    alternate: dict[Key, Place] = field(default_factory=dict)

    def lookup(self, city: str, state: str) -> tuple[Place, MatchVia] | None:
        """Main names first; an alternate name only when no main name matches."""
        key = (normalise_place_name(city), state)
        if key in self.primary:
            return self.primary[key], MatchVia.PRIMARY
        if key in self.alternate:
            return self.alternate[key], MatchVia.ALTERNATE
        return None


def normalise_place_name(name: str) -> str:
    """The one name rule for gazetteer names and price-file cities (FR-009)."""
    text = name.lower().strip().replace(".", "").replace("'", "").replace("’", "")
    tokens = [_TOKEN_MAP.get(token, token) for token in text.replace("-", " ").split()]

    joined: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "mc" and i + 1 < len(tokens):
            joined.append("mc" + tokens[i + 1])
            i += 2
        else:
            joined.append(tokens[i])
            i += 1
    return " ".join(joined)


def load_gazetteer(path: Path) -> Gazetteer:
    """Index class-P places by (normalised name, state); one winner per key (tie rule)."""
    path = Path(path)
    if not path.is_file():
        raise GazetteerMissing(path)

    gazetteer = Gazetteer()
    with open(path, encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) <= _POP or cols[_CLASS] != "P" or cols[_CODE] in EXCLUDED_FEATURE_CODES:
                continue
            place = Place(
                geonameid=int(cols[_ID]),
                name=cols[_NAME],
                state=cols[_STATE],
                lat_text=cols[_LAT],
                lng_text=cols[_LNG],
                population=int(cols[_POP] or 0),
            )
            for name in {cols[_NAME], cols[_ASCII]}:
                _keep_best(gazetteer.primary, (normalise_place_name(name), place.state), place)
            for name in cols[_ALT].split(","):
                if name:
                    _keep_best(
                        gazetteer.alternate, (normalise_place_name(name), place.state), place
                    )
    return gazetteer


def _keep_best(index: dict[Key, Place], key: Key, place: Place) -> None:
    """Tie rule: highest population, then lowest geonameid."""
    current = index.get(key)
    if current is None or (place.population, -place.geonameid) > (
        current.population,
        -current.geonameid,
    ):
        index[key] = place

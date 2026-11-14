"""Connected platforms. Adding one: a module with a `Source` subclass, an entry here,
a fixture test and a `connect-<name>` skill (see the add-source skill)."""
from .base import Source
from .goodreads import Goodreads
from .instagram import Instagram
from .karakeep import Karakeep
from .pinterest import Pinterest
from .youtube import YouTube

SOURCES: dict[str, Source] = {s.name: s for s in [Instagram(), Pinterest(), YouTube(), Goodreads(), Karakeep()]}

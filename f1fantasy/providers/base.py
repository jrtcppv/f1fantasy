from typing import Protocol

from ..models import Dataset


class Provider(Protocol):
    def fetch(self) -> Dataset: ...

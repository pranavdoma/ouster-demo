from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..frame import Frame, SensorMeta


class FrameSource(ABC):
    """A pull-based stream of lidar frames."""

    @property
    @abstractmethod
    def meta(self) -> SensorMeta: ...

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        """Yield frames until closed. May raise on connection loss."""

    def close(self) -> None:  # pragma: no cover - trivial
        pass

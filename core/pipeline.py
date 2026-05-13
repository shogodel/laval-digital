import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Raised when a pipeline station fails."""


class Station(ABC):
    """Base class for a single pipeline station.

    Subclasses must implement ``run()`` and may override ``rollback()``.
    Stations receive and return a mutable ``context`` dict.  Context flows
    through the pipeline sequentially — keys set by station N are available
    to station N+1.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        """Execute this station.

        Args:
            config: The raw deployment configuration from the caller.
            context: Mutable dict shared across all stations.
                Set any output values here so downstream stations or
                ``rollback()`` can use them.

        Raises:
            PipelineError: On any failure.
        """

    def rollback(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        """Undo the work done by ``run()``.

        Called in reverse order when a downstream station fails.
        The default is a no-op.
        """


class Pipeline:
    """Orchestrates a sequence of :class:`Station` instances with rollback.

    Usage::

        pipeline = Pipeline([
            ValidateStation(),
            SubdomainStation(),
            ...
        ])
        result = pipeline.run(config)
    """

    def __init__(self, stations: List[Station]) -> None:
        self._stations = stations

    def run(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Run all stations in order.

        Args:
            config: The raw deployment configuration.

        Returns:
            A result dict with ``success`` (bool), ``error`` (str or None),
            and any keys added to ``context`` by the stations.
        """
        context: Dict[str, Any] = {}
        completed: List[Station] = []
        result: Dict[str, Any] = {"success": False, "error": None}

        for station in self._stations:
            try:
                logger.info("Pipeline station: %s", station.name)
                station.run(config, context)
                completed.append(station)
                context.setdefault("_completed_stations", []).append(station.name)
            except PipelineError as e:
                msg = f"Station '{station.name}' failed: {e}"
                logger.error(msg)
                result["error"] = msg
                self._rollback(completed, config, context)
                result.update(context)
                result["success"] = False
                return result
            except Exception as e:
                msg = f"Station '{station.name}' raised unexpected error: {e}"
                logger.error(msg, exc_info=True)
                result["error"] = msg
                self._rollback(completed, config, context)
                result.update(context)
                result["success"] = False
                return result

        result["success"] = True
        result.update(context)
        return result

    def _rollback(
        self,
        completed: List[Station],
        config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        """Call ``rollback()`` on every completed station in reverse order."""
        for station in reversed(completed):
            try:
                station.rollback(config, context)
                logger.info("Rolled back station: %s", station.name)
            except Exception as e:
                logger.error("Rollback failed for station '%s': %s", station.name, e)

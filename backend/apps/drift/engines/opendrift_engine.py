from .base import DriftEngine, DriftInput, DriftOutput


class OpenDriftEngine(DriftEngine):
    """OpenDrift integration (not yet implemented)."""
    name = 'opendrift'

    def compute(self, params: DriftInput) -> DriftOutput:
        raise NotImplementedError(
            'OpenDrift engine is not yet implemented. '
            'Install opendrift and configure forcing data to use this engine.'
        )

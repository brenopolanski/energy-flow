"""How routes obtain the application service."""

from energyflow.disaggregation import EnergyDisaggregationService


def get_disaggregation_service() -> EnergyDisaggregationService:
    return EnergyDisaggregationService()

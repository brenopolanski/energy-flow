"""How routes obtain the reading repository and the job dispatcher."""

from fastapi import Request

from energyflow.jobs import ReadingJobDispatcher
from energyflow.persistence.repository import EnergyReadingRepository


def get_reading_repository(request: Request) -> EnergyReadingRepository:
    return request.app.state.readings


def get_job_dispatcher(request: Request) -> ReadingJobDispatcher:
    return request.app.state.jobs

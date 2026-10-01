"""HTTP application for the results service."""

from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

from results_service.postgres import PostgresResultReader, connect, database_url
from results_service.reading import ProcessedReading, ResultReader

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


def get_reader() -> ResultReader:
    raise RuntimeError("reader dependency was not overridden")


Reader = Annotated[ResultReader, Depends(get_reader)]


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/results/{reading_id}",
    response_model=ProcessedReading,
    status_code=status.HTTP_200_OK,
)
async def get_result(reading_id: UUID, reader: Reader) -> ProcessedReading:
    found = await reader.find(reading_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return found


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await connect(database_url())
    app.state.reader = PostgresResultReader(pool)
    app.dependency_overrides[get_reader] = lambda: app.state.reader
    try:
        yield
    finally:
        await pool.close()


def create_app(reader: ResultReader | None = None) -> FastAPI:
    app = FastAPI(
        title="EnergyFlow Results",
        version="0.1.0",
        lifespan=None if reader is not None else lifespan,
    )
    app.include_router(router)
    if reader is not None:
        app.dependency_overrides[get_reader] = lambda: reader
    return app


app = create_app()

"""Ingestion service.

Accepts sensor readings over HTTP, validates them, and publishes
``ReadingAccepted``. It does not disaggregate or store results.
"""

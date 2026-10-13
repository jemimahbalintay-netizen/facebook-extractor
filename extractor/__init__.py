"""Extraction package for facebook-extractor.

The public entry point for batch work is :func:`extractor.pipeline.ingest_urls`;
single-URL work goes through :func:`extractor.pipeline.process_url`.
"""

from __future__ import annotations

__all__ = ["pipeline"]

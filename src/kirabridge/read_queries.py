"""Bounded serial reads sharing one roundtrip, with fresh existing authorization."""

import asyncio
import json

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input
from kirabridge.read_query import ReadQuery, read_query_async

MAX_RESULT_BYTES = 2 * 1024 * 1024
READ_BATCH_SECONDS = 12.0


class ReadQueries(Input):
    queries: list[ReadQuery] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bound_payload(self):
        if sum(q.max_bytes for q in self.queries) > 262144:
            raise ValueError("Combined read budgets exceed 256 KiB")
        if any(q.operation == "file.list" and q.limit > 100 for q in self.queries):
            raise ValueError("Batch directory pages are limited to 100 entries")
        return self


async def read_queries(bridge, principal, request):
    request = ReadQueries.model_validate(request.model_dump())
    results, size = [], 0
    deadline = asyncio.get_running_loop().time() + READ_BATCH_SECONDS
    for index, query in enumerate(request.queries):
        if asyncio.get_running_loop().time() >= deadline:
            return {
                "results": results,
                "read_only": True,
                "complete": False,
                "next_index": index,
                "error": {"code": "read_timeout"},
            }
        try:
            async with asyncio.timeout_at(deadline):
                value = await read_query_async(bridge, principal, query)
        except BridgeError as error:
            value = {"error": {"code": error.code, "message": str(error)}}
        except TimeoutError:
            results.append(
                {"index": index, "operation": query.operation, "error": {"code": "read_timeout"}}
            )
            return {
                "results": results,
                "read_only": True,
                "complete": False,
                "next_index": index + 1,
            }
        size += len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if size > MAX_RESULT_BYTES:
            return {
                "results": results,
                "read_only": True,
                "complete": False,
                "omitted_index": index,
                "omitted_read_executed": True,
                "error": {"code": "read_result_limit"},
            }
        results.append({"index": index, "operation": query.operation, "result": value})
    return {"results": results, "read_only": True, "complete": True}

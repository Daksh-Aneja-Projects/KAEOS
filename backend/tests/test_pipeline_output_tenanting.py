"""ETL load step: nothing untenanted may reach the destination.

`_to_output_records` is the last hop before external data leaves the Data
Fabric pipeline, so every row it emits must carry the tenant - chunked or not.
"""
from app.services.pipeline_service import _to_output_records
from app.transforms.base import TransformRecord


def test_chunkless_record_becomes_one_tenanted_row():
    rec = TransformRecord(id="r1", source_record_id="s1", data={"a": 1},
                          text_content="hello", metadata={"src": "x"})
    rows = _to_output_records([rec], "tenant_a")
    assert rows == [{
        "record_id": "r1", "tenant_id": "tenant_a", "data": {"a": 1},
        "text_content": "hello",
        "metadata": {"src": "x", "tenant_id": "tenant_a"},
    }]


def test_chunks_are_tenanted_without_overwriting_an_existing_tenant():
    rec = TransformRecord(
        id="r2", source_record_id="s2", data={},
        chunks=[
            {"text": "one", "metadata": {"page": 1}},
            {"text": "two", "tenant_id": "tenant_b"},   # already stamped: left alone
        ],
    )
    rows = _to_output_records([rec], "tenant_a")
    assert rows[0]["tenant_id"] == "tenant_a"
    assert rows[0]["metadata"]["tenant_id"] == "tenant_a"
    assert rows[1]["tenant_id"] == "tenant_b"

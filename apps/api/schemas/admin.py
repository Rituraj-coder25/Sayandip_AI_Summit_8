from pydantic import BaseModel


class SourceHealthItem(BaseModel):
    name: str
    status: str
    last_success: str | None = None
    last_error: str | None = None
    items_count: str | None = None
    last_fetch_ts: float | None = None

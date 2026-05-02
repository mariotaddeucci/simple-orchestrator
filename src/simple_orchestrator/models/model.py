from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    name: str
    vendor: str
    provider: str | None = None
    description: str | None = None

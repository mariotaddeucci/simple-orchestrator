from pydantic import BaseModel


class SkillConfig(BaseModel):
    name: str
    path: str | None = None
    enabled: bool = True

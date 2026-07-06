from datetime import datetime

from pydantic import BaseModel


class TrackModRequest(BaseModel):
    game_domain: str
    mod_id: int


class ModOut(BaseModel):
    game_domain: str
    mod_id: int
    name: str
    version: str
    author: str = ""
    picture_url: str = ""
    last_checked: datetime | None = None

    model_config = {"from_attributes": True}


class ModInfoOut(BaseModel):
    game_domain: str
    mod_id: int
    name: str
    version: str
    author: str = ""
    picture_url: str = ""


class SetChannelRequest(BaseModel):
    channel_id: int

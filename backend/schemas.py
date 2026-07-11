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
    summary: str = ""
    picture_url: str = ""
    last_checked: datetime | None = None

    model_config = {"from_attributes": True}


class ModInfoOut(BaseModel):
    game_domain: str
    mod_id: int
    name: str
    version: str
    author: str = ""
    summary: str = ""
    picture_url: str = ""


class SearchResultOut(BaseModel):
    mod_id: int
    name: str
    game_domain: str


class GameOut(BaseModel):
    name: str
    domain: str


class SetChannelRequest(BaseModel):
    channel_id: int


class GuildOut(BaseModel):
    guild_id: int
    channel_id: int | None = None


class NotifyTarget(BaseModel):
    guild_id: int
    channel_id: int


class ChangedModOut(BaseModel):
    mod: ModOut
    notify: list[NotifyTarget]

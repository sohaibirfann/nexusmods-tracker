from datetime import datetime

from pydantic import BaseModel


class TrackModRequest(BaseModel):
    game_domain: str
    mod_id: int


class ModOut(BaseModel):
    game_domain: str
    game_name: str = ""
    game_image_url: str = ""
    mod_id: int
    name: str
    version: str
    author: str = ""
    summary: str = ""
    picture_url: str = ""
    endorsements: int = 0
    downloads: int = 0
    nexus_updated_at: int = 0
    last_checked: datetime | None = None

    model_config = {"from_attributes": True}


class ModInfoOut(BaseModel):
    game_domain: str
    game_name: str = ""
    game_image_url: str = ""
    mod_id: int
    name: str
    version: str
    author: str = ""
    summary: str = ""
    picture_url: str = ""
    endorsements: int = 0
    downloads: int = 0
    nexus_updated_at: int = 0


class SearchResultOut(BaseModel):
    mod_id: int
    name: str
    game_domain: str


class GameOut(BaseModel):
    name: str
    domain: str


class SetChannelRequest(BaseModel):
    channel_id: int


class SetPingRequest(BaseModel):
    role_id: int | None = None


class GuildOut(BaseModel):
    guild_id: int
    channel_id: int | None = None
    ping_role_id: int | None = None


class NotifyTarget(BaseModel):
    guild_id: int
    channel_id: int
    ping_role_id: int | None = None


class ChangedModOut(BaseModel):
    mod: ModOut
    notify: list[NotifyTarget]
    previous_version: str = ""
    endorsement_delta: int = 0
    download_delta: int = 0
    changelog: list[str] = []

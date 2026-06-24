from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ExternalLinkType = Literal["linkcore", "youtube", "spotify", "apple_music", "other"]


class NamuWikiCredit(BaseModel):
    role: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    name_ko: str | None = Field(default=None, max_length=160)


class NamuWikiExternalLink(BaseModel):
    type: ExternalLinkType = "other"
    url: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=80)


class NamuWikiLyricLine(BaseModel):
    original: str | None = Field(default=None, max_length=500)
    pronunciation_ko: str | None = Field(default=None, max_length=500)
    translation_ko: str | None = Field(default=None, max_length=500)

    @property
    def is_blank(self) -> bool:
        return not any(
            value and value.strip()
            for value in (self.original, self.pronunciation_ko, self.translation_ko)
        )


class NamuWikiSongArticleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    artist: str = Field(min_length=1, max_length=160)
    release_date: str | None = Field(default=None, max_length=40)
    album: str | None = Field(default=None, max_length=160)
    album_type: str | None = Field(default="싱글", max_length=40)
    lyricist: str | None = Field(default=None, max_length=160)
    lyricist_ko: str | None = Field(default=None, max_length=160)
    composer: str | None = Field(default=None, max_length=160)
    composer_ko: str | None = Field(default=None, max_length=160)
    arranger: str | None = Field(default=None, max_length=160)
    arranger_ko: str | None = Field(default=None, max_length=160)
    cover_file: str | None = Field(default=None, max_length=240)
    categories: list[str] = Field(default_factory=list)
    discography_template: str | None = Field(default=None, max_length=160)
    theme_song_for: str | None = Field(default=None, max_length=240)
    intro: str | None = Field(default=None, max_length=600)
    youtube_url: str | None = Field(default=None, max_length=500)
    external_links: list[NamuWikiExternalLink] = Field(default_factory=list)
    extra_credits: list[NamuWikiCredit] = Field(default_factory=list)
    title_image_dark: str | None = Field(default=None, max_length=240)
    title_image_light: str | None = Field(default=None, max_length=240)
    lyrics: list[NamuWikiLyricLine] = Field(default_factory=list)

    @field_validator("categories", mode="before")
    @classmethod
    def normalize_categories(cls, value):
        if value is None:
            return []
        return value


class NamuWikiSongArticleResponse(BaseModel):
    text: str


class NamuWikiTemplateSongArticleRequest(BaseModel):
    template_example: str = Field(min_length=1, max_length=30000)
    song: NamuWikiSongArticleRequest
    extra_instruction: str | None = Field(default=None, max_length=1000)


class NamuWikiTemplateCreate(BaseModel):
    template_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=160)
    template_example: str = Field(min_length=1, max_length=30000)
    description: str | None = Field(default=None, max_length=500)


class NamuWikiTemplateInfo(BaseModel):
    template_id: str
    name: str
    description: str | None = None


class NamuWikiTemplateDetail(NamuWikiTemplateInfo):
    template_example: str


class NamuWikiSavedTemplateSongArticleRequest(BaseModel):
    template_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    song: NamuWikiSongArticleRequest
    extra_instruction: str | None = Field(default=None, max_length=1000)

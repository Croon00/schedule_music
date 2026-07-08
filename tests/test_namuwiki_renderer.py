from app.namuwiki.models import (
    NamuWikiCredit,
    NamuWikiExternalLink,
    NamuWikiLyricLine,
    NamuWikiSongArticleRequest,
)
from app.namuwiki.renderer import render_song_article


def test_render_song_article_in_namuwiki_markup() -> None:
    text = render_song_article(
        NamuWikiSongArticleRequest(
            categories=["일본 노래", "2021년 노래"],
            discography_template="HACHI 디스코그래피",
            title="Greyword",
            artist="HACHI",
            album="Greyword",
            album_type="싱글",
            release_date="2021. 06. 30.",
            lyricist="富岡征士郎",
            lyricist_ko="토미오카 세이시로",
            composer="柳川 和樹",
            composer_ko="야나가와 카즈키",
            cover_file="Cover_Greyword.jpg",
            theme_song_for="모바일 게임 [[거짓된 앨리스]]",
            youtube_url="https://www.youtube.com/watch?v=c7m6kAGEw3U",
            external_links=[
                NamuWikiExternalLink(type="youtube", url="https://www.youtube.com/watch?v=c7m6kAGEw3U"),
                NamuWikiExternalLink(type="spotify", url="https://open.spotify.com/album/example"),
            ],
            extra_credits=[
                NamuWikiCredit(role="영상", name="ノノル", name_ko="노노루"),
            ],
            title_image_dark="GreywordW.svg",
            title_image_light="GreywordB.svg",
            lyrics=[
                NamuWikiLyricLine(
                    original="重なる傷痕　逃げ惑う影",
                    pronunciation_ko="카사나루 키즈아토 니게마토우 카게",
                    translation_ko="쌓여가는 상처, 우왕좌왕하는 그림자",
                ),
                NamuWikiLyricLine(),
                NamuWikiLyricLine(
                    original="世界さえ壊せる",
                    pronunciation_ko="세카이사에 코와세루",
                    translation_ko="세계마저 부술 수 있어",
                ),
            ],
        )
    )

    assert text.startswith("[[분류:일본 노래]][[분류:2021년 노래]]")
    assert "[include(틀:HACHI 디스코그래피)]" in text
    assert "'''{{{+1 Greyword}}}'''" in text
    assert "[[파일:Cover_Greyword.jpg|width=100%]]" in text
    assert "富岡征士郎 {{{-5 | 토미오카 세이시로}}}" in text
    assert "[youtube(c7m6kAGEw3U)]" in text
    assert "모바일 게임 [[거짓된 앨리스]] 테마곡." in text
    assert "[[파일:GreywordW.svg|width=200&theme=dark]]" in text
    assert "'''重なる傷痕　逃げ惑う影'''" in text
    assert "{{{#b1b1b1,#7f7f7f 카사나루 키즈아토 니게마토우 카게}}}" in text
    assert text.endswith("[br] ||\n")


def test_render_song_article_with_optional_credit_fields() -> None:
    text = render_song_article(
        NamuWikiSongArticleRequest(
            title="Song",
            artist="Artist",
            lyricist="Lyricist",
            composer="Composer",
            arranger="Arranger",
            illustrator="Illustrator",
            video="Video Team",
            producer="Producer",
            executive_producer="Executive Producer",
            recording_director="Recording Director",
            recording_mixing="Recording Mixer",
            extra_credits=[
                NamuWikiCredit(role="Guitar", name="Guitarist", name_ko="기타리스트"),
            ],
        )
    )

    assert "'''작사''' ||||Lyricist" in text
    assert "'''작곡''' ||||Composer" in text
    assert "'''편곡''' ||||Arranger" in text
    assert "'''일러스트''' ||||<width=300>Illustrator" in text
    assert "'''영상''' ||||<width=300>Video Team" in text
    assert "'''프로듀서''' ||||<width=300>Producer" in text
    assert "'''제작 총괄''' ||||<width=300>Executive Producer" in text
    assert "'''레코딩 총괄''' ||||<width=300>Recording Director" in text
    assert "'''레코딩 & 믹싱''' ||||<width=300>Recording Mixer" in text
    assert "'''Guitar''' ||||<width=300>Guitarist {{{-5 | 기타리스트}}}" in text

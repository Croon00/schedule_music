from app.integrations.youtube_archive_labels import clean_label, label_key


def test_numbered_song_aliases_share_a_translation():
    assert label_key('02.  アイドル') == label_key('アイドル')
    assert label_key('いきのこり●ぼくら') == label_key('いきのこり ぼくら')
    assert clean_label('366日') == '366日'
    assert clean_label('10月無口な君を忘れる') == '10月無口な君を忘れる'

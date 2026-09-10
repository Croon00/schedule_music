import { describe, expect, it } from 'vitest'
import type { YouTubeLiveArchive, YouTubePerformance } from '@/api/types'
import { buildSongStats } from './songStats'

function archive(id: number, title: string, korean: string | null = null, artistKo: string | null = null): YouTubeLiveArchive {
  return {
    id, youtube_url: `https://www.youtube.com/watch?v=${id}`, video_title: '歌枠',
    artist_name: 'HACHI', status: 'ready', published_at: null, broadcast_at: null,
    last_checked_at: null, setlist: [], performances: [{
      id, song_title: title, song_title_ko: korean, original_artist: '青葉市子', original_artist_ko: artistKo,
      start_seconds: 0, timestamp_text: '0:00',
    } as YouTubePerformance],
  }
}

describe('full archive statistics', () => {
  it('counts older broadcasts beyond the first hundred before sorting or rendering', () => {
    const rows = Array.from({ length: 123 }, (_, index) => archive(index, 'いきのこり●ぼくら'))
    const stats = buildSongStats(rows, '', 'asc')
    expect(stats[0]?.count).toBe(123)
    expect(stats[0]?.occurrences).toHaveLength(123)
  })
  it('uses a later translation and keeps it when a shorter untranslated title appears', () => {
    const rows = [archive(1, 'いきのこり●ぼくら'), archive(2, 'いきのこり ぼくら', '살아남은 우리', '아오바 이치코'), archive(3, 'いきのこりぼくら')]
    const stats = buildSongStats(rows, '살아남은', 'desc')
    expect(stats).toHaveLength(1)
    expect(stats[0]).toMatchObject({ count: 3, titleKo: '살아남은 우리', originalArtistKo: '아오바 이치코' })
    expect(buildSongStats(rows, '아오바', 'asc')).toHaveLength(1)
  })
  it('finds the song despite the decorative dot in its stored title', () => {
    expect(buildSongStats([archive(1, 'いきのこり●ぼくら')], 'いきのこり ぼくら', 'asc')).toHaveLength(1)
  })
})

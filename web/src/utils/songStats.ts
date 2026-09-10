import type { YouTubeLiveArchive } from '@/api/types'
import { searchKey } from './archiveFilters'

export type SongStatOccurrence = {
  archiveId: number; youtubeUrl: string; videoTitle: string | null
  broadcastAt: string | null; publishedAt: string | null; startSeconds: number; timestampText: string
}
export type SongStat = {
  title: string; titleKo: string | null; originalArtist: string | null; originalArtistKo: string | null
  count: number; occurrences: SongStatOccurrence[]
  artistCandidates: Record<string, { originalArtist: string; originalArtistKo: string | null; count: number }>
}

function normalizeSongTitle(value: string): string {
  let title = value
    .normalize('NFKC')
    .replace(/[\u200B-\u200D\uFEFF]/gu, ' ')
    .replace(/\s+/gu, ' ')
    .trim()

  // 댓글/셋리스트에서 흔히 붙는 표기를 제거한다. 실제 곡명은 표시용으로 유지한다.
  title = title
    .replace(/^\s*[「『【［(（]\s*/u, '')
    .replace(/\s*[」』】］)）]\s*$/u, '')
    .replace(/\s*[（(［\[]\s*(?:cover|\u6b4c\u3063\u3066\u307f\u305f|\u30ab\u30d0\u30fc|\u5f3e\u304d\u8a9e\u308a|acoustic(?:\s+(?:ver(?:sion)?|version))?|original|\u30aa\u30ea\u30b8\u30ca\u30eb)\s*[）)］\]]\s*$/iu, '')
    .replace(/\s*(?:[-\u2013\u2014|\uff5c/\uff0f:\uff1a]\s*|\s+)(?:cover|\u6b4c\u3063\u3066\u307f\u305f|\u30ab\u30d0\u30fc|\u5f3e\u304d\u8a9e\u308a|acoustic(?:\s+(?:ver(?:sion)?|version))?|original|\u30aa\u30ea\u30b8\u30ca\u30eb)\s*$/iu, '')

  return stripSetlistAttribution(title).trim()
}

const PERFORMANCE_NOTE = /(?:cover|\u6b4c\u3063\u3066\u307f\u305f|\u30ab\u30d0\u30fc|\u5f3e\u304d\u8a9e\u308a|\u30d4\u30a2\u30ce|\u30ae\u30bf\u30fc|acoustic|live|\u97f3\u6e90|inst(?:rumental)?|original|\u30aa\u30ea\u30b8\u30ca\u30eb)/iu
const JAPANESE_TEXT = /[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}]/u

function stripSetlistAttribution(value: string): string {
  let title = value

  // Drop a trailing performance note, but never parentheses that are part of
  // the actual title unless they clearly describe a cover/arrangement.
  while (true) {
    const match = title.match(/\s*[\uff08(]\s*([^\uff09)]{1,80})\s*[\uff09)]\s*$/u)
    if (!match || !PERFORMANCE_NOTE.test(match[1])) break
    title = title.slice(0, match.index).trim()
  }

  // Setlists frequently append the original artist or singer after a slash.
  // Strip it when it is explicitly a performance label, or when a Latin title
  // has a Japanese credit (for example, `rain stops, good-bye / \u306b\u304aP`).
  const slashMatch = title.match(/^(?<song>.+?)\s*[/\uff0f|\uff5c]\s*(?<credit>[^/\uff0f|\uff5c]{1,40})$/u)
  if (slashMatch?.groups) {
    const { song, credit } = slashMatch.groups
    if (PERFORMANCE_NOTE.test(credit) || (/[A-Za-z]/u.test(song) && JAPANESE_TEXT.test(credit))) {
      title = song.trim()
    }
  }

  return title
}

function songStatsKey(title: string): string {
  return searchKey(title)
}

function cleanSongTitle(value: string): string | null {
  const title = normalizeSongTitle(value)
  if (!title || /^start(?:\b|[：:\-])/i.test(title)) return null
  const withoutIndex = title.replace(/^(?:#\s*)?(?:제\s*)?\d+\s*(?:곡목?|曲目?)?\s*(?:[.．:：\-—)]\s*)+/u, '').trim()
  return withoutIndex && !/^start(?:\b|[：:\-])/i.test(withoutIndex) ? withoutIndex : null
}
function addSongStatArtistCandidate(song: SongStat, originalArtist: string | null, originalArtistKo: string | null): void {
  if (!originalArtist) return
  const key = songStatsKey(originalArtist)
  if (!key) return
  const candidate = song.artistCandidates[key]
  if (candidate) {
    candidate.count += 1
    candidate.originalArtistKo ||= originalArtistKo
  }
  else song.artistCandidates[key] = { originalArtist, originalArtistKo, count: 1 }
}
export function buildSongStats(archives: YouTubeLiveArchive[], search: string, sort: 'asc' | 'desc'): SongStat[] {
  const songs = new Map<string, SongStat>()
  for (const archive of archives) {
    const entries = archive.performances?.length
      ? archive.performances.map((performance) => ({
          title: performance.song_title,
          titleKo: performance.song_title_ko,
          originalArtist: performance.original_artist,
          originalArtistKo: performance.original_artist_ko,
          startSeconds: performance.start_seconds,
          timestampText: performance.timestamp_text,
        }))
      : (archive.setlist ?? []).map((entry) => ({
          title: entry.title, titleKo: null, originalArtist: null, originalArtistKo: null,
          startSeconds: timestampToSeconds(entry.timestamp), timestampText: entry.timestamp,
        }))
    for (const entry of entries) {
      const title = cleanSongTitle(entry.title)
      if (!title) continue
      const key = songStatsKey(title)
      const song = songs.get(key)
      if (song) {
        song.count += 1
        song.occurrences.push({
          archiveId: archive.id, youtubeUrl: archive.youtube_url, videoTitle: archive.video_title,
          broadcastAt: archive.broadcast_at, publishedAt: archive.published_at,
          startSeconds: entry.startSeconds, timestampText: entry.timestampText,
        })
        // 같은 곡의 표기가 여러 개면, 보통 더 짧은 쪽이 주석이 덜 붙은 제목이다.
        if (title.length < song.title.length) {
          song.title = title
          song.titleKo = entry.titleKo || song.titleKo
        }
        song.titleKo ||= entry.titleKo
        addSongStatArtistCandidate(song, entry.originalArtist, entry.originalArtistKo)
      }
      else {
        const song: SongStat = {
          title,
          titleKo: entry.titleKo,
          originalArtist: entry.originalArtist,
          originalArtistKo: entry.originalArtistKo,
          count: 1,
          occurrences: [{
          archiveId: archive.id, youtubeUrl: archive.youtube_url, videoTitle: archive.video_title,
          broadcastAt: archive.broadcast_at, publishedAt: archive.published_at,
          startSeconds: entry.startSeconds, timestampText: entry.timestampText,
          }],
          artistCandidates: {},
        }
        addSongStatArtistCandidate(song, entry.originalArtist, entry.originalArtistKo)
        songs.set(key, song)
      }
    }
  }
  const query = searchKey(search)
  return [...songs.values()]
    .map((song) => {
      const primaryArtist = Object.values(song.artistCandidates)
        .sort((left, right) => right.count - left.count)[0]
      if (primaryArtist) {
        song.originalArtist = primaryArtist.originalArtist
        song.originalArtistKo = primaryArtist.originalArtistKo
      }
      return song
    })
    .filter((song) => !query || [song.title, song.titleKo, song.originalArtist, song.originalArtistKo].some(value => searchKey(value || '').includes(query)))
    .sort((left, right) => sort === 'asc'
      ? left.count - right.count || left.title.localeCompare(right.title)
      : right.count - left.count || left.title.localeCompare(right.title))
}

function timestampToSeconds(value: string): number {
  const parts = value.split(':').map((part) => Number(part.trim()))
  if (!parts.length || parts.some((part) => !Number.isFinite(part))) return 0
  return parts.reduce((total, part) => total * 60 + part, 0)
}

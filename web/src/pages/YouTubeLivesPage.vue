<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Artist, YouTubeLiveArchive, YouTubePerformance, YouTubePerformanceSearchResult } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import PageHeader from '@/components/PageHeader.vue'

type SongStatOccurrence = {
  archiveId: number; youtubeUrl: string; videoTitle: string | null
  broadcastAt: string | null; publishedAt: string | null; startSeconds: number; timestampText: string
}
type SongStat = {
  title: string; titleKo: string | null; originalArtist: string | null; originalArtistKo: string | null
  count: number; occurrences: SongStatOccurrence[]
  artistCandidates: Record<string, { originalArtist: string; originalArtistKo: string | null; count: number }>
}

const queryClient = useQueryClient()
const route = useRoute()
const router = useRouter()
const selectedArtistId = computed(() => {
  const value = Number(route.params.artistId)
  return Number.isFinite(value) && value > 0 ? value : null
})
const agencyFilter = ref('all')
const topTab = ref<'artists' | 'search'>('artists')
const viewMode = ref<'grid' | 'list'>('grid')
const collectionMode = ref<'lives' | 'stats'>('lives')
const songQuery = ref('')
const statsSort = ref<'asc' | 'desc'>('asc')
const registrationOpen = ref(false)
const detailOpen = ref(false)
const statsDetailOpen = ref(false)
const selectedStatSong = ref<SongStat | null>(null)
const selectedStatOccurrence = ref<SongStatOccurrence | null>(null)
const selectedId = ref<number | null>(null)
const playerStartSeconds = ref(0)
const playerNonce = ref(0)
const youtubeUrl = ref('')
const artistName = ref('')
const searchMode = ref<'artist' | 'song'>('song')
const searchModeOptions = [
  { label: '아티스트', value: 'artist' },
  { label: '곡 제목', value: 'song' },
]
const searchText = ref('')
const searchResults = ref<YouTubePerformanceSearchResult[]>([])
const selectedSearchArtists = ref<string[]>([])
const selectedSearchSongs = ref<string[]>([])
const selectedOriginalArtists = ref<string[]>([])
const artistFilterInput = ref('')
const songFilterInput = ref('')
const originalArtistFilterInput = ref('')
const editingPerformanceId = ref<number | null>(null)
const performanceDraft = ref({ song_title: '', song_title_ko: '', original_artist: '', original_artist_ko: '' })

const artistsQuery = useQuery({ queryKey: ['artists'], queryFn: api.artists.list })
const agenciesQuery = useQuery({ queryKey: ['artist-agencies'], queryFn: api.artistAgencies.list })
const performanceFilters = useQuery({ queryKey: ['youtube-performance-filters'], queryFn: api.youtubePerformances.filters })
const vtubers = computed(() => (artistsQuery.data.value ?? []).filter((artist) =>
  artist.artist_kind === 'vtuber' && artist.show_in_youtube_lives,
))
const artists = computed(() => vtubers.value.filter((artist) => agencyFilter.value === 'all' || artist.agency === agencyFilter.value))
const selectedArtist = computed(() => artists.value.find((artist) => artist.id === selectedArtistId.value) ?? null)
const archives = useQuery({
  queryKey: computed(() => ['youtube-lives', selectedArtist.value?.name ?? '']),
  queryFn: () => api.youtubeLives.list(selectedArtist.value?.name),
  enabled: computed(() => selectedArtist.value !== null),
})
const detail = useQuery({
  queryKey: computed(() => ['youtube-live', selectedId.value]),
  queryFn: () => api.youtubeLives.get(selectedId.value!),
  enabled: computed(() => detailOpen.value && selectedId.value !== null),
})

const addLive = useMutation({
  mutationFn: () => api.youtubeLives.create(youtubeUrl.value, artistName.value),
  onSuccess: async (archive) => {
    youtubeUrl.value = ''
    registrationOpen.value = false
    const matched = artists.value.find((artist) => artistNameMatches(artist, archive.artist_name))
    if (matched) router.push(`/youtube-lives/artists/${matched.id}`)
    selectedId.value = archive.id
    detailOpen.value = true
    queryClient.setQueryData(['youtube-live', archive.id], archive)
    await queryClient.invalidateQueries({ queryKey: ['youtube-lives'] })
  },
})
const searchPerformances = useMutation({
  mutationFn: () => api.youtubePerformances.search({
    artists: selectedSearchArtists.value,
    songs: selectedSearchSongs.value,
    originalArtists: selectedOriginalArtists.value,
  }),
  onSuccess: (rows) => { searchResults.value = rows },
})
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
  // 공백, 전각/반각, 문장부호의 차이는 같은 곡으로 간주한다.
  return title
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[\p{P}\p{Z}\p{Cf}]/gu, '')
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
  if (candidate) candidate.count += 1
  else song.artistCandidates[key] = { originalArtist, originalArtistKo, count: 1 }
}
const songStats = computed(() => {
  const songs = new Map<string, SongStat>()
  for (const archive of archives.data.value ?? []) {
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
          song.titleKo = entry.titleKo
        }
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
  const query = songQuery.value.trim().toLocaleLowerCase()
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
    .filter((song) => !query || song.title.toLocaleLowerCase().includes(query))
    .sort((left, right) => statsSort.value === 'asc'
      ? left.count - right.count || left.title.localeCompare(right.title)
      : right.count - left.count || left.title.localeCompare(right.title))
})
const updatePerformance = useMutation({
  mutationFn: () => api.youtubePerformances.update(editingPerformanceId.value!, performanceDraft.value),
  onSuccess: async () => {
    editingPerformanceId.value = null
    await queryClient.invalidateQueries({ queryKey: ['youtube-live'] })
    await queryClient.invalidateQueries({ queryKey: ['youtube-lives'] })
  },
})

function artistNameMatches(artist: Artist, name: string): boolean {
  return [artist.name, artist.display_name].filter(Boolean).some((value) => value?.toLowerCase() === name.toLowerCase())
}
function selectArtist(artist: Artist): void {
  router.push(`/youtube-lives/artists/${artist.id}`)
  selectedId.value = null
  detailOpen.value = false
}
function openRegistration(): void {
  artistName.value = selectedArtist.value?.name || ''
  registrationOpen.value = true
}
function openArchive(archive: YouTubeLiveArchive): void {
  // Korean labels can be backfilled by the detail API for older setlists.
  // Discard a previously opened archive's cache so reopening it always shows
  // the newly completed title/artist labels.
  queryClient.removeQueries({ queryKey: ['youtube-live', archive.id] })
  selectedId.value = archive.id
  playerStartSeconds.value = 0
  playerNonce.value += 1
  detailOpen.value = true
}
function addSearchFilter(target: 'artist' | 'song' | 'originalArtist'): void {
  const fields = {
    artist: [artistFilterInput, selectedSearchArtists],
    song: [songFilterInput, selectedSearchSongs],
    originalArtist: [originalArtistFilterInput, selectedOriginalArtists],
  } as const
  const [input, selected] = fields[target]
  const value = input.value.trim()
  if (value && !selected.value.includes(value)) selected.value.push(value)
  input.value = ''
}
function removeSearchFilter(target: 'artist' | 'song' | 'originalArtist', value: string): void {
  const selected = target === 'artist' ? selectedSearchArtists : target === 'song' ? selectedSearchSongs : selectedOriginalArtists
  selected.value = selected.value.filter((item) => item !== value)
}
function submitSongSearch(): void {
  addSearchFilter('song')
  addSearchFilter('artist')
  addSearchFilter('originalArtist')
  if (selectedSearchSongs.value.length) searchPerformances.mutate()
}
function timestampToSeconds(value: string): number {
  const parts = value.split(':').map((part) => Number(part.trim()))
  if (!parts.length || parts.some((part) => !Number.isFinite(part))) return 0
  return parts.reduce((total, part) => total * 60 + part, 0)
}
function openSongStats(song: SongStat): void {
  selectedStatSong.value = song
  selectedStatOccurrence.value = null
  statsDetailOpen.value = true
}
function playStatOccurrence(occurrence: SongStatOccurrence): void {
  selectedStatOccurrence.value = occurrence
}
function displayOccurrenceDate(occurrence: SongStatOccurrence): string {
  const value = occurrence.broadcastAt || occurrence.publishedAt
  return value ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'long' }).format(new Date(value)) : '날짜 미확인'
}
function pairedLabel(original: string | null, korean: string | null): string {
  return korean ? `${original || '미상'} (${korean})` : (original || '미상')
}
function startPerformanceEdit(song: YouTubePerformance): void {
  editingPerformanceId.value = song.id
  performanceDraft.value = {
    song_title: song.song_title,
    song_title_ko: song.song_title_ko || '',
    original_artist: song.original_artist || '',
    original_artist_ko: song.original_artist_ko || '',
  }
}
function displayDate(archive: YouTubeLiveArchive): string {
  const value = archive.broadcast_at || archive.published_at
  return value ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'long' }).format(new Date(value)) : '날짜 미확인'
}
function youtubeVideoId(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (parsed.hostname.includes('youtu.be')) return parsed.pathname.split('/').filter(Boolean)[0] ?? null
    if (parsed.pathname.startsWith('/live/')) return parsed.pathname.split('/')[2] ?? null
    if (parsed.pathname.startsWith('/shorts/')) return parsed.pathname.split('/')[2] ?? null
    return parsed.searchParams.get('v')
  } catch { return null }
}
function thumbnail(archive: YouTubeLiveArchive): string | undefined {
  const id = youtubeVideoId(archive.youtube_url)
  return id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : undefined
}
function youtubeEmbedUrl(archive: YouTubeLiveArchive, startSeconds = 0): string | undefined {
  return youtubeEmbedUrlFromUrl(archive.youtube_url, startSeconds)
}
function youtubeEmbedUrlFromUrl(url: string, startSeconds = 0): string | undefined {
  const id = youtubeVideoId(url)
  if (!id) return undefined
  const params = new URLSearchParams({ autoplay: '1', rel: '0' })
  if (startSeconds > 0) params.set('start', String(startSeconds))
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?${params}`
}
function playPerformance(startSeconds: number): void {
  playerStartSeconds.value = startSeconds
  playerNonce.value += 1
}
function playTimestampFromLink(event: MouseEvent): void {
  const target = event.target as HTMLElement | null
  const link = target?.closest<HTMLAnchorElement>('a[href]')
  if (!link || !detail.data.value) return
  try {
    const url = new URL(link.href)
    const startSeconds = Number(url.searchParams.get('t')?.replace(/s$/, ''))
    if (Number.isFinite(startSeconds) && startSeconds >= 0) {
      event.preventDefault()
      playPerformance(startSeconds)
    }
  } catch {
    // Keep the normal link behaviour for URLs that cannot be parsed.
  }
}
function artistImage(artist: Artist): string | undefined {
  if (artist.spotify_image_url) return artist.spotify_image_url
  const xSource = artist.sources.find((source) => source.source_type === 'x')
  if (xSource) {
    const username = xSource.value.includes('/')
      ? xSource.value.split('/').filter(Boolean).pop()
      : xSource.value.replace(/^@/, '')
    if (username) return `https://unavatar.io/x/${encodeURIComponent(username)}`
  }
  const id = artist.representative_youtube_url ? youtubeVideoId(artist.representative_youtube_url) : null
  return id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : undefined
}
function hideBrokenImage(event: Event): void {
  const image = event.currentTarget as HTMLImageElement
  image.style.display = 'none'
}
</script>

<template>
  <div class="page youtube-page">
    <PageHeader
      eyebrow="YOUTUBE LIVE ARCHIVE"
      title="우타와꾸 노래 기록"
      description="등록된 아티스트별 우타와꾸와 방송 셋리스트를 모아봅니다."
    />

    <div v-if="!selectedArtist" class="youtube-top-tabs" role="tablist">
      <UButton :class="{ active: topTab === 'artists' }" @click="topTab = 'artists'">아티스트 목록</UButton>
      <UButton :class="{ active: topTab === 'search' }" @click="topTab = 'search'">노래 검색</UButton>
    </div>
    <div v-if="!selectedArtist && topTab === 'artists'" class="agency-filter youtube-agency-filter" aria-label="VTuber 소속 선택">
      <UButton :class="{ active: agencyFilter === 'all' }" @click="agencyFilter = 'all'">전체</UButton>
      <UButton v-for="agency in agenciesQuery.data.value || []" :key="agency.id" :class="{ active: agencyFilter === agency.name }" @click="agencyFilter = agency.name">
        {{ agency.name === 'KAMITSUBAKI STUDIO' ? 'KAMITSUBAKI' : agency.name }}
      </UButton>
    </div>

    <section v-if="!selectedArtist && topTab === 'artists'" class="artist-section">
      <div class="section-heading">
        <div><p class="eyebrow">SELECT ARTIST</p><h2>아티스트</h2></div>
        <span class="count-label">{{ artists.length }} ARTISTS</span>
      </div>
      <div v-if="artistsQuery.isPending.value" class="artist-selector artist-selector--grid"><i v-for="n in 8" :key="n" class="artist-select-card loading" /></div>
      <div v-else-if="artists.length" class="artist-selector artist-selector--grid">
        <UButton v-for="artist in artists" :key="artist.id" class="artist-select-card" :class="{ active: artist.id === selectedArtistId }" @click="selectArtist(artist)">
          <span class="artist-image"><b>{{ (artist.display_name || artist.name).slice(0, 1) }}</b><img v-if="artistImage(artist)" :src="artistImage(artist)" :alt="artist.display_name || artist.name" @error="hideBrokenImage" /></span>
          <strong>{{ artist.display_name || artist.name }}</strong>
          <small>{{ artist.sources.length }} SOURCES</small>
        </UButton>
      </div>
      <div v-else class="empty-state"><strong>등록된 아티스트가 없습니다</strong><p>먼저 아티스트 관리에서 아티스트를 등록하세요.</p></div>
      <small v-if="artists.length" class="avatar-credit">프로필 이미지: X · unavatar</small>
    </section>

    <section v-if="!selectedArtist && topTab === 'search'" class="song-search panel">
      <div class="song-search__header"><p class="eyebrow">SONG SEARCH</p><h2>우타와꾸 노래 검색</h2><p>각 조건에서 여러 항목을 추가해 검색할 수 있습니다.</p></div>
      <form class="song-search__form" @submit.prevent="submitSongSearch">
        <label>곡 제목<div class="filter-input"><UInput v-model="songFilterInput" list="song-suggestions" placeholder="원제 또는 한국어 제목 입력" @keydown.enter.prevent="addSearchFilter('song')" /><UButton type="button" @click="addSearchFilter('song')">추가</UButton></div><datalist id="song-suggestions"><option v-for="song in performanceFilters.data.value?.songs || []" :key="song" :value="song" /></datalist><div class="filter-chips"><span v-for="song in selectedSearchSongs" :key="song">{{ song }} <button type="button" @click="removeSearchFilter('song', song)">×</button></span></div></label>
        <label>부른 아티스트<div class="filter-input"><UInput v-model="artistFilterInput" list="artist-suggestions" placeholder="아티스트 입력" @keydown.enter.prevent="addSearchFilter('artist')" /><UButton type="button" @click="addSearchFilter('artist')">추가</UButton></div><datalist id="artist-suggestions"><option v-for="artist in performanceFilters.data.value?.performers || []" :key="artist" :value="artist" /></datalist><div class="filter-chips"><span v-for="artist in selectedSearchArtists" :key="artist">{{ artist }} <button type="button" @click="removeSearchFilter('artist', artist)">×</button></span></div></label>
        <label>원곡 가수<div class="filter-input"><UInput v-model="originalArtistFilterInput" list="original-artist-suggestions" placeholder="원문 또는 한국어 이름 입력" @keydown.enter.prevent="addSearchFilter('originalArtist')" /><UButton type="button" @click="addSearchFilter('originalArtist')">추가</UButton></div><datalist id="original-artist-suggestions"><option v-for="artist in performanceFilters.data.value?.original_artists || []" :key="artist" :value="artist" /></datalist><div class="filter-chips"><span v-for="artist in selectedOriginalArtists" :key="artist">{{ artist }} <button type="button" @click="removeSearchFilter('originalArtist', artist)">×</button></span></div></label>
        <UButton type="submit" class="button button--primary song-search__submit" :disabled="searchPerformances.isPending.value || (!selectedSearchSongs.length && !songFilterInput.trim())">검색</UButton>
      </form>
      <p v-if="searchPerformances.error.value" class="form-error">{{ searchPerformances.error.value?.message }}</p>
      <div v-if="searchResults.length" class="performance-results"><table class="data-table"><thead><tr><th>날짜</th><th>부른 아티스트</th><th>곡 제목</th><th>원곡 가수</th></tr></thead><tbody><tr v-for="row in searchResults" :key="row.id"><td>{{ row.performed_on }}</td><td>{{ row.artist_name }}</td><td><strong>{{ pairedLabel(row.song_title, row.song_title_ko) }}</strong></td><td>{{ pairedLabel(row.original_artist, row.original_artist_ko) }}</td></tr></tbody></table></div>
      <div v-else-if="searchPerformances.isSuccess.value" class="empty-state compact"><strong>검색 결과가 없습니다.</strong></div>
    </section>

    <section v-if="selectedArtist" class="youtube-artist-hero">
      <span class="artist-image"><b>{{ (selectedArtist.display_name || selectedArtist.name).slice(0, 1) }}</b><img v-if="artistImage(selectedArtist)" :src="artistImage(selectedArtist)" :alt="selectedArtist.display_name || selectedArtist.name" @error="hideBrokenImage" /></span>
      <div><p class="eyebrow">{{ selectedArtist.agency || 'VTUBER' }}</p><h1>{{ selectedArtist.display_name || selectedArtist.name }}</h1><span>UTAWAKU ARCHIVE</span></div>
      <UButton class="collection-toggle" @click="collectionMode = collectionMode === 'lives' ? 'stats' : 'lives'">{{ collectionMode === 'lives' ? '통계' : 'Live Collection' }}</UButton>
    </section>

    <section v-if="selectedArtist && collectionMode === 'lives'" class="archive-heading">
      <div>
        <p class="eyebrow">LIVE COLLECTION</p>
        <h2>{{ selectedArtist?.display_name || selectedArtist?.name || '우타와꾸' }}</h2>
        <p>저장된 방송을 선택하면 타임스탬프별 셋리스트를 확인할 수 있습니다.</p>
      </div>
      <div class="archive-actions">
        <span class="count-label">{{ archives.data.value?.length || 0 }} LIVES</span>
        <div class="view-toggle" aria-label="보기 방식">
          <UButton :class="{ active: viewMode === 'grid' }" aria-label="카드 보기" @click="viewMode = 'grid'">▦</UButton>
          <UButton :class="{ active: viewMode === 'list' }" aria-label="목록 보기" @click="viewMode = 'list'">☷</UButton>
        </div>
      </div>
    </section>

    <div v-if="selectedArtist && collectionMode === 'lives' && archives.isPending.value" class="archive-grid"><i v-for="n in 6" :key="n" class="archive-card loading" /></div>
    <div v-else-if="selectedArtist && collectionMode === 'lives' && archives.isError.value" class="alert alert--error">우타와꾸 기록을 불러오지 못했습니다.</div>
    <div v-else-if="selectedArtist && collectionMode === 'lives' && !archives.data.value?.length" class="panel empty-state"><span>♫</span><strong>저장된 우타와꾸가 없습니다</strong><p>오른쪽 아래 등록 버튼으로 첫 방송을 추가할 수 있습니다.</p></div>
    <div v-else-if="selectedArtist && collectionMode === 'lives'" :class="viewMode === 'grid' ? 'archive-grid' : 'archive-list'">
      <UButton v-for="archive in archives.data.value" :key="archive.id" :class="viewMode === 'grid' ? 'archive-card' : 'archive-row'" @click="openArchive(archive)">
        <div class="archive-cover">
          <img v-if="thumbnail(archive)" :src="thumbnail(archive)" :alt="archive.video_title || archive.artist_name" />
          <span v-else>▶</span>
          <b>{{ archive.setlist?.length || 0 }}곡</b>
        </div>
        <div class="archive-meta">
          <small>{{ displayDate(archive) }} · {{ archive.status === 'ready' ? '셋리스트 준비됨' : '댓글 확인 대기' }}</small>
          <strong>{{ archive.video_title || archive.artist_name }}</strong>
          <span>{{ archive.artist_name }}</span>
        </div>
      </UButton>
    </div>

    <section v-if="selectedArtist && collectionMode === 'stats'" class="song-stats panel">
      <div class="song-stats__header">
        <div><p class="eyebrow">SONG STATISTICS</p><h2>우타와꾸 곡 통계</h2><p>방송 셋리스트에서 집계한 곡별 누적 횟수입니다.</p></div>
        <span class="count-label">{{ songStats.length }} SONGS</span>
      </div>
      <div class="song-stats__toolbar">
        <UInput v-model="songQuery" placeholder="곡 제목 검색" aria-label="곡 제목 검색" />
        <UButton class="song-sort" @click="statsSort = statsSort === 'asc' ? 'desc' : 'asc'">{{ statsSort === 'asc' ? '횟수 오름차순' : '횟수 내림차순' }}</UButton>
      </div>
      <div v-if="archives.isPending.value" class="empty-state compact"><strong>곡 통계를 준비하고 있습니다.</strong></div>
      <div v-else-if="!songStats.length" class="empty-state compact"><strong>표시할 곡 통계가 없습니다.</strong></div>
      <ol v-else class="song-stats__list"><li v-for="(song, index) in songStats" :key="song.title"><span>{{ index + 1 }}</span><button type="button" class="song-stats__title" @click="openSongStats(song)"><strong>{{ pairedLabel(song.title, song.titleKo) }}</strong><small v-if="song.originalArtist">{{ pairedLabel(song.originalArtist, song.originalArtistKo) }}</small></button><b>{{ song.count }}회</b></li></ol>
    </section>

    <AppModal :open="statsDetailOpen" :title="selectedStatSong ? pairedLabel(selectedStatSong.title, selectedStatSong.titleKo) : '곡 가창 기록'" :description="selectedStatSong ? `${selectedStatSong.count}회 가창 기록` : ''" @close="statsDetailOpen = false">
      <div v-if="selectedStatSong" class="song-history">
        <p v-if="selectedStatSong.originalArtist" class="song-history__artist">{{ pairedLabel(selectedStatSong.originalArtist, selectedStatSong.originalArtistKo) }}</p>
        <div v-if="selectedStatOccurrence && youtubeEmbedUrlFromUrl(selectedStatOccurrence.youtubeUrl, selectedStatOccurrence.startSeconds)" class="video-player">
          <iframe :key="`${selectedStatOccurrence.archiveId}-${selectedStatOccurrence.startSeconds}`" :src="youtubeEmbedUrlFromUrl(selectedStatOccurrence.youtubeUrl, selectedStatOccurrence.startSeconds)" :title="selectedStatOccurrence.videoTitle || selectedStatSong.title" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen />
        </div>
        <ol class="song-history__list">
          <li v-for="occurrence in selectedStatSong.occurrences" :key="`${occurrence.archiveId}-${occurrence.startSeconds}`">
            <span><strong>{{ displayOccurrenceDate(occurrence) }}</strong><small>{{ occurrence.videoTitle || 'YouTube Live' }}</small></span>
            <UButton class="button button--ghost" @click="playStatOccurrence(occurrence)">{{ occurrence.timestampText }} 재생</UButton>
          </li>
        </ol>
      </div>
    </AppModal>

    <details v-if="false" class="panel performance-search-panel">
      <summary><span><b>전체 가창 기록 검색</b><small>아티스트 또는 곡 제목으로 모든 방송을 검색합니다.</small></span><em>열기</em></summary>
      <form class="performance-search" @submit.prevent="searchPerformances.mutate()">
        <USelect v-model="searchMode" :items="searchModeOptions" />
        <UInput v-model="searchText" required :placeholder="searchMode === 'artist' ? '예: HACHI' : '예: アポリア'" />
        <UButton class="button button--primary" :disabled="searchPerformances.isPending.value">검색</UButton>
      </form>
      <p v-if="searchPerformances.error.value" class="form-error">{{ searchPerformances.error.value?.message }}</p>
      <div v-if="searchResults.length" class="performance-results">
        <table class="data-table"><thead><tr><th>날짜</th><th>아티스트</th><th>곡 / 원곡 가수</th><th>영상</th></tr></thead><tbody>
          <tr v-for="row in searchResults" :key="row.id"><td>{{ row.performed_on }}</td><td><strong>{{ row.artist_name }}</strong></td><td><strong>{{ pairedLabel(row.song_title, row.song_title_ko) }}</strong><span>{{ pairedLabel(row.original_artist, row.original_artist_ko) }}</span></td><td><a :href="`${row.youtube_url}&t=${row.start_seconds}s`" target="_blank" rel="noreferrer" class="text-link">{{ row.timestamp_text }}</a></td></tr>
        </tbody></table>
      </div>
      <div v-else-if="searchPerformances.isSuccess.value" class="empty-state compact"><strong>검색된 가창 기록이 없습니다</strong></div>
    </details>

    <UButton v-if="selectedArtist" class="floating-register" aria-label="우타와꾸 추가" @click="openRegistration">우타와꾸 추가</UButton>

    <AppModal :open="registrationOpen" title="우타와꾸 등록" description="아티스트와 YouTube URL을 입력하면 방송 정보와 댓글 셋리스트를 저장합니다." @close="registrationOpen = false">
      <form class="form-grid" @submit.prevent="addLive.mutate()">
        <label class="form-grid__wide">아티스트 이름
          <UInput v-model="artistName" list="registered-artists" required placeholder="예: HACHI" />
          <datalist id="registered-artists"><option v-for="artist in vtubers" :key="artist.id" :value="artist.name">{{ artist.display_name || artist.name }}</option></datalist>
        </label>
        <label class="form-grid__wide">YouTube URL<UInput v-model="youtubeUrl" type="url" required placeholder="https://www.youtube.com/watch?v=..." /></label>
        <p v-if="addLive.error.value" class="form-error">{{ addLive.error.value.message }}</p>
        <div class="form-actions"><UButton type="button" class="button button--ghost" @click="registrationOpen = false">취소</UButton><UButton class="button button--primary" :disabled="addLive.isPending.value">{{ addLive.isPending.value ? '셋리스트 확인 중…' : '등록' }}</UButton></div>
      </form>
    </AppModal>

    <AppModal :open="detailOpen" content-class="modal--youtube-detail" :title="detail.data.value?.video_title || detail.data.value?.artist_name || '셋리스트'" :description="detail.data.value ? `${displayDate(detail.data.value)} · ${detail.data.value.performances?.length || 0}곡` : '방송 정보를 불러오고 있습니다.'" @close="detailOpen = false">
      <div v-if="detail.isPending.value" class="skeleton-list"><i /><i /><i /></div>
      <div v-else-if="detail.isError.value" class="alert alert--error">셋리스트를 불러오지 못했습니다.</div>
      <div v-else-if="detail.data.value" class="live-detail" @click.capture="playTimestampFromLink">
        <a :href="detail.data.value.youtube_url" target="_blank" rel="noreferrer" class="video-link video-link--compact">▶ YouTube에서 열기</a>
        <div v-if="youtubeEmbedUrl(detail.data.value, playerStartSeconds)" class="video-player">
          <iframe
            :key="`${detail.data.value.id}-${playerStartSeconds}-${playerNonce}`"
            :src="youtubeEmbedUrl(detail.data.value, playerStartSeconds)"
            :title="detail.data.value.video_title || detail.data.value.artist_name"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowfullscreen
          />
        </div>
        <UScrollArea v-if="detail.data.value.performances?.length" class="setlist-scroll" shadow>
          <ol class="setlist-list">
          <li v-for="song in detail.data.value.performances" :key="song.id">
            <a :href="`${detail.data.value.youtube_url}&t=${song.start_seconds}s`" target="_blank" rel="noreferrer">{{ song.timestamp_text }}</a>
            <template v-if="editingPerformanceId === song.id">
              <span class="performance-editor"><UInput v-model="performanceDraft.song_title" placeholder="곡 제목" /><UInput v-model="performanceDraft.song_title_ko" placeholder="곡 제목 (한국어)" /><UInput v-model="performanceDraft.original_artist" placeholder="원곡 가수" /><UInput v-model="performanceDraft.original_artist_ko" placeholder="원곡 가수 (한국어)" /><p v-if="updatePerformance.error.value" class="form-error">{{ updatePerformance.error.value.message }}</p></span>
              <span class="edit-actions"><UButton class="button button--primary" :disabled="updatePerformance.isPending.value" @click="updatePerformance.mutate()">저장</UButton><UButton class="button button--ghost" @click="editingPerformanceId = null">취소</UButton></span>
            </template>
            <template v-else><span><strong>{{ pairedLabel(song.song_title, song.song_title_ko) }}</strong><small>{{ pairedLabel(song.original_artist, song.original_artist_ko) }}</small></span><span><UButton class="edit-button" @click="startPerformanceEdit(song)">수정</UButton></span></template>
          </li>
          </ol>
        </UScrollArea>
        <div v-else class="empty-state compact"><strong>아직 저장된 셋리스트가 없습니다</strong><p>댓글 확인이 끝나면 곡 목록이 표시됩니다.</p></div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.artist-section{margin-bottom:36px}.section-heading,.archive-heading{display:flex;align-items:end;justify-content:space-between;gap:20px}.section-heading{margin-bottom:13px}.section-heading h2,.archive-heading h2{margin:0}.artist-selector{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(145px,190px);gap:10px;overflow-x:auto;padding:3px 2px 12px}.artist-select-card{min-height:112px;padding:16px;border:1px solid var(--line);border-radius:11px;color:#8b98ad;background:var(--panel);text-align:left;cursor:pointer;transition:.2s}.artist-select-card>span{display:grid;place-items:center;width:34px;height:34px;margin-bottom:13px;border:1px solid rgba(50,214,255,.24);border-radius:9px;color:var(--cyan);background:rgba(50,214,255,.06);font:700 12px ui-monospace,monospace}.artist-select-card strong,.artist-select-card small{display:block}.artist-select-card strong{overflow:hidden;color:#d9e3ef;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.artist-select-card small{margin-top:6px;color:#56647a;font:8px ui-monospace,monospace}.artist-select-card:hover,.artist-select-card.active{transform:translateY(-2px);border-color:rgba(50,214,255,.45);background:linear-gradient(145deg,rgba(50,214,255,.1),rgba(154,124,255,.04));box-shadow:0 12px 30px rgba(0,0,0,.2)}.loading{background:linear-gradient(100deg,#101622 20%,#1a2230 40%,#101622 60%);background-size:200%;animation:shimmer 1.5s infinite}.archive-heading{margin-bottom:17px;padding-top:22px;border-top:1px solid var(--line)}.archive-heading>div>p:last-child{margin:8px 0 0;color:#6f7d92;font-size:10px}.archive-actions{display:flex;align-items:center;gap:13px}.view-toggle{display:flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}.view-toggle button{width:38px;height:34px;border:0;border-right:1px solid var(--line);color:#657287;background:transparent;cursor:pointer}.view-toggle button:last-child{border-right:0}.view-toggle button.active{color:var(--cyan);background:rgba(50,214,255,.08)}.archive-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(245px,1fr));gap:15px}.archive-card,.archive-row{padding:0;border:1px solid var(--line);border-radius:11px;overflow:hidden;color:inherit;background:var(--panel);text-align:left;cursor:pointer;transition:.22s}.archive-card:hover,.archive-row:hover{transform:translateY(-3px);border-color:rgba(50,214,255,.35);box-shadow:0 16px 36px rgba(0,0,0,.24)}.archive-cover{position:relative;aspect-ratio:16/9;display:grid;place-items:center;overflow:hidden;color:var(--cyan);background:#0d1420;font-size:25px}.archive-cover img{width:100%;height:100%;object-fit:cover;transition:transform .3s}.archive-card:hover img,.archive-row:hover img{transform:scale(1.035)}.archive-cover b{position:absolute;right:9px;bottom:9px;padding:5px 7px;border-radius:5px;color:white;background:rgba(4,7,12,.82);font:700 8px ui-monospace,monospace}.archive-meta{padding:14px}.archive-meta small,.archive-meta strong,.archive-meta span{display:block}.archive-meta small{color:#607087;font:8px ui-monospace,monospace}.archive-meta strong{display:-webkit-box;overflow:hidden;margin-top:8px;color:#dae4ef;font-size:12px;line-height:1.45;-webkit-box-orient:vertical;-webkit-line-clamp:2}.archive-meta span{margin-top:8px;color:#758399;font-size:9px}.archive-list{display:grid;gap:8px}.archive-row{display:grid;grid-template-columns:190px 1fr;align-items:center}.archive-row .archive-cover{aspect-ratio:16/9}.performance-search-panel{margin-top:28px}.performance-search-panel summary{display:flex;justify-content:space-between;cursor:pointer;list-style:none}.performance-search-panel summary b,.performance-search-panel summary small{display:block}.performance-search-panel summary b{font-size:12px}.performance-search-panel summary small{margin-top:6px;color:#657287;font-size:9px}.performance-search-panel summary em{color:var(--cyan);font:normal 9px ui-monospace,monospace}.performance-search-panel[open] summary{margin-bottom:20px}.performance-search{display:grid;grid-template-columns:150px 1fr auto;gap:10px}.performance-results{overflow:auto;margin-top:16px}.performance-results td span{display:block;opacity:.65;margin-top:4px}.floating-register{position:fixed;right:30px;bottom:28px;z-index:40;display:flex;align-items:center;gap:9px;padding:13px 17px;border:1px solid rgba(50,214,255,.55);border-radius:999px;color:#061219;background:linear-gradient(135deg,#5ce0ff,#25bfe9);box-shadow:0 15px 40px rgba(25,190,230,.25);font-size:11px;font-weight:800;cursor:pointer}.floating-register span{font-size:18px;line-height:1}.video-link{position:relative;display:block;overflow:hidden;margin-bottom:18px;border-radius:9px;background:#0a1019}.video-link img{display:block;width:100%;max-height:270px;object-fit:cover;opacity:.75}.video-link>span{position:absolute;inset:auto 14px 13px;color:white;font-size:10px;font-weight:800}.setlist-list{list-style:none;padding:0;margin:0;display:grid}.setlist-list li{display:grid;grid-template-columns:5rem 1fr auto;gap:1rem;padding:.8rem 0;border-bottom:1px solid var(--line)}.setlist-list a{color:var(--cyan)}.setlist-list small{display:block;margin-top:4px;color:#68768b}.karaoke-numbers{line-height:1.6;white-space:nowrap}.empty-state.compact{min-height:120px}@media(max-width:800px){.archive-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.archive-row{grid-template-columns:120px 1fr}.performance-search{grid-template-columns:1fr}.floating-register{right:18px;bottom:18px}.setlist-list li{grid-template-columns:4rem 1fr}.karaoke-numbers{display:none}}@media(max-width:520px){.archive-grid{grid-template-columns:1fr}.artist-selector{grid-auto-columns:135px}}
.artist-select-card>.artist-image{position:relative;width:52px;height:52px;overflow:hidden;border-radius:50%}.artist-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.artist-image b{font:700 12px ui-monospace,monospace}.avatar-credit{display:block;margin-top:2px;color:#48566c;font-size:10px;text-align:right}
.artist-selector--grid{grid-template-columns:repeat(4,minmax(0,1fr))}.artist-selector--grid .artist-select-card{min-height:210px;padding:20px}.artist-selector--grid .artist-select-card strong{font-size:15px}.artist-selector--grid .artist-select-card small{font-size:10px}.artist-selector--grid .artist-select-card>.artist-image{width:92px;height:92px}
@media(max-width:1100px){.artist-selector--grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
.artist-selector--grid{grid-auto-flow:row;grid-auto-columns:auto;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));overflow:visible;padding-bottom:0}.artist-selector--grid .artist-select-card{min-height:190px}.artist-selector--grid .artist-select-card>.artist-image{width:82px;height:82px}.youtube-agency-filter{margin-top:0}.youtube-artist-hero{display:grid;grid-template-columns:130px minmax(0,1fr) auto;align-items:end;gap:22px;margin-bottom:26px;padding:20px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(135deg,rgba(50,214,255,.08),rgba(255,255,255,.015))}.youtube-artist-hero>.artist-image{position:relative;display:grid;place-items:center;width:130px;height:130px;overflow:hidden;border-radius:12px;color:var(--cyan);background:rgba(50,214,255,.08);font-size:32px}.youtube-artist-hero h1{margin:5px 0 8px;font-size:28px}.youtube-artist-hero div>span{color:#718096;font:700 9px ui-monospace,monospace}@media(max-width:700px){.artist-selector--grid{grid-template-columns:repeat(2,minmax(0,1fr))}.youtube-artist-hero{grid-template-columns:88px 1fr;align-items:center}.youtube-artist-hero>.artist-image{width:88px;height:88px}.youtube-artist-hero>.button{grid-column:1/-1}}
.performance-editor{display:grid;gap:7px}.edit-actions{display:flex;gap:6px;align-items:start}.edit-button{display:block;margin-top:7px;padding:2px 5px;border:1px solid var(--line);border-radius:4px;color:var(--cyan);background:transparent;font-size:9px;cursor:pointer}
.floating-register{padding:10px 14px;font-size:12px;transition:color .2s ease,background .2s ease,border-color .2s ease,box-shadow .2s ease}.floating-register:hover{color:#dff9ff;border-color:#6be6ff;background:#113344;box-shadow:0 0 0 3px rgba(50,214,255,.2),0 10px 26px rgba(25,190,230,.3);transform:none}
.artist-selector--grid{grid-template-columns:repeat(4,minmax(0,1fr))}.artist-selector--grid .artist-select-card{min-height:210px;padding:20px}.artist-selector--grid .artist-select-card strong{font-size:15px}.artist-selector--grid .artist-select-card small{font-size:10px}.artist-selector--grid .artist-select-card>.artist-image{width:92px;height:92px}@media(max-width:1100px){.artist-selector--grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:700px){.artist-selector--grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.video-link--compact{width:max-content;margin:0 0 10px;padding:7px 10px;border:1px solid var(--line);border-radius:7px;color:var(--cyan);background:rgba(50,214,255,.05);font-size:10px}.live-detail{display:grid;gap:12px}.live-detail .video-player{height:min(52vh,620px);min-height:320px;margin:0;aspect-ratio:auto}.live-detail .setlist-list{max-height:30vh;overflow-y:auto;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.015);scrollbar-gutter:stable}.live-detail .setlist-list li{padding:.9rem 0}.live-detail .setlist-list li:last-child{border-bottom:0}:global(.modal.modal--youtube-detail){width:min(1180px,calc(100vw - 32px));max-width:min(1180px,calc(100vw - 32px))}@media(max-width:700px){.live-detail .video-player{height:auto;min-height:0;aspect-ratio:16/9}.live-detail .setlist-list{max-height:34vh;padding:0 8px}}
.archive-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.archive-meta small{font-size:11px;line-height:1.45}.archive-meta span{font-size:11px}.archive-meta strong{font-size:14px}@media(max-width:1100px){.archive-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:700px){.archive-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.youtube-agency-filter{gap:10px}.youtube-agency-filter button{min-height:42px;padding:0 18px;font-size:13px}
.youtube-top-tabs{display:flex;gap:8px;margin:0 0 14px}.youtube-top-tabs button{min-height:42px;padding:0 18px;border:1px solid var(--line);color:#8fa0b5;background:rgba(255,255,255,.02)}.youtube-top-tabs button.active{color:#061a10;border-color:#4de6a8;background:#4de6a8}.song-search{margin-top:20px}.song-search__header p:last-child{margin:8px 0 0;color:#7a879a;font-size:13px}.song-search__form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:22px}.song-search label{display:grid;gap:8px;color:#b4c2d3;font-size:13px;font-weight:700}.filter-input{display:flex;gap:7px}.filter-input>*:first-child{flex:1}.filter-input button{min-height:40px;padding:0 12px;color:#a4f3c8;border:1px solid rgba(77,230,168,.35);background:rgba(77,230,168,.07)}.filter-chips{display:flex;flex-wrap:wrap;gap:6px;min-height:27px}.filter-chips span{display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border-radius:999px;color:#baf5ce;background:rgba(77,230,168,.1);font-size:11px}.filter-chips button{padding:0;border:0;color:#baf5ce;background:transparent;font-size:16px;line-height:1;cursor:pointer}.song-search__submit{grid-column:1/-1;justify-self:end}@media(max-width:900px){.song-search__form{grid-template-columns:1fr}.song-search__submit{width:100%}}
.collection-toggle{align-self:start;padding:10px 16px;color:#8eeebc;border:1px solid rgba(77,230,168,.4);border-radius:8px;background:rgba(77,230,168,.07);font-size:13px;font-weight:800}.collection-toggle:hover{color:#061a10;border-color:#4de6a8;background:#4de6a8;box-shadow:0 0 0 3px rgba(77,230,168,.14)}.song-stats{margin-top:22px}.song-stats__header{display:flex;align-items:end;justify-content:space-between;gap:20px;padding-bottom:20px;border-bottom:1px solid var(--line)}.song-stats__header h2{margin:0}.song-stats__header p:last-child{margin:8px 0 0;color:#7a879a;font-size:13px}.song-stats__toolbar{display:flex;gap:10px;margin:18px 0}.song-stats__toolbar>*:first-child{flex:1}.song-sort{min-height:40px;padding:0 15px;color:#baf5ce;border:1px solid rgba(77,230,168,.35);background:rgba(77,230,168,.07);font-size:12px}.song-sort:hover{color:#061a10;border-color:#4de6a8;background:#4de6a8}.song-stats__list{display:grid;gap:4px;padding:0;margin:0;list-style:none}.song-stats__list li{display:grid;grid-template-columns:42px minmax(0,1fr) auto;align-items:center;gap:14px;padding:14px 10px;border-bottom:1px solid var(--line)}.song-stats__list li>span{color:#66758a;font:700 12px ui-monospace,monospace}.song-stats__list strong{overflow:hidden;color:#dce7f5;font-size:15px;text-overflow:ellipsis;white-space:nowrap}.song-stats__list b{padding:5px 9px;border-radius:999px;color:#9cf1c5;background:rgba(77,230,168,.1);font-size:12px}@media(max-width:700px){.youtube-artist-hero{grid-template-columns:88px minmax(0,1fr)}.collection-toggle{grid-column:1/-1;justify-self:stretch}.song-stats__header{align-items:start;flex-direction:column}.song-stats__toolbar{flex-direction:column}.song-sort{width:100%}}
.video-player{aspect-ratio:16/9;overflow:hidden;margin-bottom:18px;border-radius:9px;background:#0a1019}.video-player iframe{display:block;width:100%;height:100%;border:0}
.live-detail .video-player{height:min(48vh,560px);min-height:320px;margin:0;aspect-ratio:auto}.live-detail .setlist-list{max-height:none;overflow:visible;padding:0 12px;border:0;border-radius:0;background:transparent}.setlist-scroll{max-height:26vh;overflow-y:auto;border:1px solid rgba(50,214,255,.2);border-radius:9px;background:linear-gradient(90deg,rgba(50,214,255,.035),rgba(255,255,255,.015));scrollbar-color:#30c7e8 rgba(50,214,255,.05);scrollbar-width:thin}.setlist-scroll::-webkit-scrollbar{width:10px}.setlist-scroll::-webkit-scrollbar-track{margin:7px 2px;border-radius:999px;background:rgba(50,214,255,.05)}.setlist-scroll::-webkit-scrollbar-thumb{border:2px solid #111927;border-radius:999px;background:linear-gradient(#6be6ff,#2baed4)}.setlist-scroll::-webkit-scrollbar-thumb:hover{background:linear-gradient(#a2f1ff,#40c8eb)}:global(.modal.modal--youtube-detail){overflow:hidden}@media(max-width:700px){.live-detail .video-player{height:auto;min-height:0;aspect-ratio:16/9}.setlist-scroll{max-height:30vh}.live-detail .setlist-list{padding:0 8px}}
.song-stats__title{display:grid;gap:4px;min-width:0;padding:0;border:0;color:inherit;background:transparent;text-align:left;cursor:pointer}.song-stats__title:hover strong{color:var(--cyan)}.song-stats__title small,.song-history__artist{color:#718096;font-size:11px}.song-history{display:grid;gap:14px}.song-history__artist{margin:0}.song-history__list{display:grid;gap:7px;padding:0;margin:0;list-style:none}.song-history__list li{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid var(--line)}.song-history__list span{display:grid;gap:4px;min-width:0}.song-history__list small{overflow:hidden;color:#718096;text-overflow:ellipsis;white-space:nowrap}.song-history__list .button{flex:0 0 auto}
</style>

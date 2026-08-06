<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Artist, YouTubeLiveArchive, YouTubePerformanceSearchResult } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import PageHeader from '@/components/PageHeader.vue'

const queryClient = useQueryClient()
const route = useRoute()
const router = useRouter()
const selectedArtistId = computed(() => {
  const value = Number(route.params.artistId)
  return Number.isFinite(value) && value > 0 ? value : null
})
const agencyFilter = ref('all')
const viewMode = ref<'grid' | 'list'>('grid')
const registrationOpen = ref(false)
const detailOpen = ref(false)
const selectedId = ref<number | null>(null)
const youtubeUrl = ref('')
const artistName = ref('')
const searchMode = ref<'artist' | 'song'>('song')
const searchText = ref('')
const searchResults = ref<YouTubePerformanceSearchResult[]>([])

const artistsQuery = useQuery({ queryKey: ['artists'], queryFn: api.artists.list })
const agenciesQuery = useQuery({ queryKey: ['artist-agencies'], queryFn: api.artistAgencies.list })
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
  mutationFn: () => searchMode.value === 'artist'
    ? api.youtubePerformances.byArtist(searchText.value)
    : api.youtubePerformances.bySong(searchText.value),
  onSuccess: (rows) => { searchResults.value = rows },
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
  selectedId.value = archive.id
  detailOpen.value = true
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

    <div v-if="!selectedArtist" class="agency-filter youtube-agency-filter" aria-label="VTuber 소속 선택">
      <button :class="{ active: agencyFilter === 'all' }" @click="agencyFilter = 'all'">전체</button>
      <button v-for="agency in agenciesQuery.data.value || []" :key="agency.id" :class="{ active: agencyFilter === agency.name }" @click="agencyFilter = agency.name">
        {{ agency.name === 'KAMITSUBAKI STUDIO' ? 'KAMITSUBAKI' : agency.name }}
      </button>
    </div>

    <section v-if="!selectedArtist" class="artist-section">
      <div class="section-heading">
        <div><p class="eyebrow">SELECT ARTIST</p><h2>아티스트</h2></div>
        <span class="count-label">{{ artists.length }} ARTISTS</span>
      </div>
      <div v-if="artistsQuery.isPending.value" class="artist-selector artist-selector--grid"><i v-for="n in 8" :key="n" class="artist-select-card loading" /></div>
      <div v-else-if="artists.length" class="artist-selector artist-selector--grid">
        <button v-for="artist in artists" :key="artist.id" class="artist-select-card" :class="{ active: artist.id === selectedArtistId }" @click="selectArtist(artist)">
          <span class="artist-image"><b>{{ (artist.display_name || artist.name).slice(0, 1) }}</b><img v-if="artistImage(artist)" :src="artistImage(artist)" :alt="artist.display_name || artist.name" @error="hideBrokenImage" /></span>
          <strong>{{ artist.display_name || artist.name }}</strong>
          <small>{{ artist.sources.length }} SOURCES</small>
        </button>
      </div>
      <div v-else class="empty-state"><strong>등록된 아티스트가 없습니다</strong><p>먼저 아티스트 관리에서 아티스트를 등록하세요.</p></div>
      <small v-if="artists.length" class="avatar-credit">프로필 이미지: X · unavatar</small>
    </section>

    <section v-if="selectedArtist" class="youtube-artist-hero">
      <span class="artist-image"><b>{{ (selectedArtist.display_name || selectedArtist.name).slice(0, 1) }}</b><img v-if="artistImage(selectedArtist)" :src="artistImage(selectedArtist)" :alt="selectedArtist.display_name || selectedArtist.name" @error="hideBrokenImage" /></span>
      <div><p class="eyebrow">{{ selectedArtist.agency || 'VTUBER' }}</p><h1>{{ selectedArtist.display_name || selectedArtist.name }}</h1><span>UTAWAKU ARCHIVE</span></div>
      <RouterLink to="/youtube-lives" class="button button--ghost">← VTuber 목록</RouterLink>
    </section>

    <section v-if="selectedArtist" class="archive-heading">
      <div>
        <p class="eyebrow">LIVE COLLECTION</p>
        <h2>{{ selectedArtist?.display_name || selectedArtist?.name || '우타와꾸' }}</h2>
        <p>저장된 방송을 선택하면 타임스탬프별 셋리스트를 확인할 수 있습니다.</p>
      </div>
      <div class="archive-actions">
        <span class="count-label">{{ archives.data.value?.length || 0 }} LIVES</span>
        <div class="view-toggle" aria-label="보기 방식">
          <button :class="{ active: viewMode === 'grid' }" aria-label="카드 보기" @click="viewMode = 'grid'">▦</button>
          <button :class="{ active: viewMode === 'list' }" aria-label="목록 보기" @click="viewMode = 'list'">☷</button>
        </div>
      </div>
    </section>

    <div v-if="selectedArtist && archives.isPending.value" class="archive-grid"><i v-for="n in 6" :key="n" class="archive-card loading" /></div>
    <div v-else-if="selectedArtist && archives.isError.value" class="alert alert--error">우타와꾸 기록을 불러오지 못했습니다.</div>
    <div v-else-if="selectedArtist && !archives.data.value?.length" class="panel empty-state"><span>♫</span><strong>저장된 우타와꾸가 없습니다</strong><p>오른쪽 아래 등록 버튼으로 첫 방송을 추가할 수 있습니다.</p></div>
    <div v-else-if="selectedArtist" :class="viewMode === 'grid' ? 'archive-grid' : 'archive-list'">
      <button v-for="archive in archives.data.value" :key="archive.id" :class="viewMode === 'grid' ? 'archive-card' : 'archive-row'" @click="openArchive(archive)">
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
      </button>
    </div>

    <details v-if="selectedArtist" class="panel performance-search-panel">
      <summary><span><b>전체 가창 기록 검색</b><small>아티스트 또는 곡 제목으로 모든 방송을 검색합니다.</small></span><em>열기</em></summary>
      <form class="performance-search" @submit.prevent="searchPerformances.mutate()">
        <select v-model="searchMode"><option value="artist">아티스트</option><option value="song">곡 제목</option></select>
        <input v-model="searchText" required :placeholder="searchMode === 'artist' ? '예: HACHI' : '예: アポリア'" />
        <button class="button button--primary" :disabled="searchPerformances.isPending.value">검색</button>
      </form>
      <p v-if="searchPerformances.error.value" class="form-error">{{ searchPerformances.error.value.message }}</p>
      <div v-if="searchResults.length" class="performance-results">
        <table class="data-table"><thead><tr><th>날짜</th><th>아티스트</th><th>곡 / 원곡 가수</th><th>노래방 번호</th><th>영상</th></tr></thead><tbody>
          <tr v-for="row in searchResults" :key="row.id"><td>{{ row.performed_on }}</td><td><strong>{{ row.artist_name }}</strong></td><td><strong>{{ row.song_title }}</strong><span>{{ row.original_artist || '원곡 가수 미상' }}</span></td><td>TJ {{ row.tj_number }}<br />금영 {{ row.ky_number }}</td><td><a :href="`${row.youtube_url}&t=${row.start_seconds}s`" target="_blank" rel="noreferrer" class="text-link">{{ row.timestamp_text }}</a></td></tr>
        </tbody></table>
      </div>
      <div v-else-if="searchPerformances.isSuccess.value" class="empty-state compact"><strong>검색된 가창 기록이 없습니다</strong></div>
    </details>

    <button v-if="selectedArtist" class="floating-register" aria-label="우타와꾸 등록" @click="openRegistration"><span>＋</span> 우타와꾸 등록</button>

    <AppModal :open="registrationOpen" title="우타와꾸 등록" description="아티스트와 YouTube URL을 입력하면 방송 정보와 댓글 셋리스트를 저장합니다." @close="registrationOpen = false">
      <form class="form-grid" @submit.prevent="addLive.mutate()">
        <label class="form-grid__wide">아티스트 이름
          <input v-model="artistName" list="registered-artists" required placeholder="예: HACHI" />
          <datalist id="registered-artists"><option v-for="artist in vtubers" :key="artist.id" :value="artist.name">{{ artist.display_name || artist.name }}</option></datalist>
        </label>
        <label class="form-grid__wide">YouTube URL<input v-model="youtubeUrl" type="url" required placeholder="https://www.youtube.com/watch?v=..." /></label>
        <p v-if="addLive.error.value" class="form-error">{{ addLive.error.value.message }}</p>
        <div class="form-actions"><button type="button" class="button button--ghost" @click="registrationOpen = false">취소</button><button class="button button--primary" :disabled="addLive.isPending.value">{{ addLive.isPending.value ? '셋리스트 확인 중…' : '등록' }}</button></div>
      </form>
    </AppModal>

    <AppModal :open="detailOpen" :title="detail.data.value?.video_title || detail.data.value?.artist_name || '셋리스트'" :description="detail.data.value ? `${displayDate(detail.data.value)} · ${detail.data.value.performances?.length || 0}곡` : '방송 정보를 불러오고 있습니다.'" @close="detailOpen = false">
      <div v-if="detail.isPending.value" class="skeleton-list"><i /><i /><i /></div>
      <div v-else-if="detail.isError.value" class="alert alert--error">셋리스트를 불러오지 못했습니다.</div>
      <div v-else-if="detail.data.value" class="live-detail">
        <a :href="detail.data.value.youtube_url" target="_blank" rel="noreferrer" class="video-link"><img v-if="thumbnail(detail.data.value)" :src="thumbnail(detail.data.value)" alt="" /><span>▶ YouTube에서 열기</span></a>
        <ol v-if="detail.data.value.performances?.length" class="setlist-list">
          <li v-for="song in detail.data.value.performances" :key="song.id"><a :href="`${detail.data.value.youtube_url}&t=${song.start_seconds}s`" target="_blank" rel="noreferrer">{{ song.timestamp_text }}</a><span><strong>{{ song.song_title }}</strong><small>{{ song.original_artist || '원곡 가수 미상' }}</small></span><span class="karaoke-numbers">TJ {{ song.tj_number }}<br />금영 {{ song.ky_number }}</span></li>
        </ol>
        <div v-else class="empty-state compact"><strong>아직 저장된 셋리스트가 없습니다</strong><p>댓글 확인이 끝나면 곡 목록이 표시됩니다.</p></div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.artist-section{margin-bottom:36px}.section-heading,.archive-heading{display:flex;align-items:end;justify-content:space-between;gap:20px}.section-heading{margin-bottom:13px}.section-heading h2,.archive-heading h2{margin:0}.artist-selector{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(145px,190px);gap:10px;overflow-x:auto;padding:3px 2px 12px}.artist-select-card{min-height:112px;padding:16px;border:1px solid var(--line);border-radius:11px;color:#8b98ad;background:var(--panel);text-align:left;cursor:pointer;transition:.2s}.artist-select-card>span{display:grid;place-items:center;width:34px;height:34px;margin-bottom:13px;border:1px solid rgba(50,214,255,.24);border-radius:9px;color:var(--cyan);background:rgba(50,214,255,.06);font:700 12px ui-monospace,monospace}.artist-select-card strong,.artist-select-card small{display:block}.artist-select-card strong{overflow:hidden;color:#d9e3ef;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.artist-select-card small{margin-top:6px;color:#56647a;font:8px ui-monospace,monospace}.artist-select-card:hover,.artist-select-card.active{transform:translateY(-2px);border-color:rgba(50,214,255,.45);background:linear-gradient(145deg,rgba(50,214,255,.1),rgba(154,124,255,.04));box-shadow:0 12px 30px rgba(0,0,0,.2)}.loading{background:linear-gradient(100deg,#101622 20%,#1a2230 40%,#101622 60%);background-size:200%;animation:shimmer 1.5s infinite}.archive-heading{margin-bottom:17px;padding-top:22px;border-top:1px solid var(--line)}.archive-heading>div>p:last-child{margin:8px 0 0;color:#6f7d92;font-size:10px}.archive-actions{display:flex;align-items:center;gap:13px}.view-toggle{display:flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}.view-toggle button{width:38px;height:34px;border:0;border-right:1px solid var(--line);color:#657287;background:transparent;cursor:pointer}.view-toggle button:last-child{border-right:0}.view-toggle button.active{color:var(--cyan);background:rgba(50,214,255,.08)}.archive-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(245px,1fr));gap:15px}.archive-card,.archive-row{padding:0;border:1px solid var(--line);border-radius:11px;overflow:hidden;color:inherit;background:var(--panel);text-align:left;cursor:pointer;transition:.22s}.archive-card:hover,.archive-row:hover{transform:translateY(-3px);border-color:rgba(50,214,255,.35);box-shadow:0 16px 36px rgba(0,0,0,.24)}.archive-cover{position:relative;aspect-ratio:16/9;display:grid;place-items:center;overflow:hidden;color:var(--cyan);background:#0d1420;font-size:25px}.archive-cover img{width:100%;height:100%;object-fit:cover;transition:transform .3s}.archive-card:hover img,.archive-row:hover img{transform:scale(1.035)}.archive-cover b{position:absolute;right:9px;bottom:9px;padding:5px 7px;border-radius:5px;color:white;background:rgba(4,7,12,.82);font:700 8px ui-monospace,monospace}.archive-meta{padding:14px}.archive-meta small,.archive-meta strong,.archive-meta span{display:block}.archive-meta small{color:#607087;font:8px ui-monospace,monospace}.archive-meta strong{display:-webkit-box;overflow:hidden;margin-top:8px;color:#dae4ef;font-size:12px;line-height:1.45;-webkit-box-orient:vertical;-webkit-line-clamp:2}.archive-meta span{margin-top:8px;color:#758399;font-size:9px}.archive-list{display:grid;gap:8px}.archive-row{display:grid;grid-template-columns:190px 1fr;align-items:center}.archive-row .archive-cover{aspect-ratio:16/9}.performance-search-panel{margin-top:28px}.performance-search-panel summary{display:flex;justify-content:space-between;cursor:pointer;list-style:none}.performance-search-panel summary b,.performance-search-panel summary small{display:block}.performance-search-panel summary b{font-size:12px}.performance-search-panel summary small{margin-top:6px;color:#657287;font-size:9px}.performance-search-panel summary em{color:var(--cyan);font:normal 9px ui-monospace,monospace}.performance-search-panel[open] summary{margin-bottom:20px}.performance-search{display:grid;grid-template-columns:150px 1fr auto;gap:10px}.performance-results{overflow:auto;margin-top:16px}.performance-results td span{display:block;opacity:.65;margin-top:4px}.floating-register{position:fixed;right:30px;bottom:28px;z-index:40;display:flex;align-items:center;gap:9px;padding:13px 17px;border:1px solid rgba(50,214,255,.55);border-radius:999px;color:#061219;background:linear-gradient(135deg,#5ce0ff,#25bfe9);box-shadow:0 15px 40px rgba(25,190,230,.25);font-size:11px;font-weight:800;cursor:pointer}.floating-register span{font-size:18px;line-height:1}.video-link{position:relative;display:block;overflow:hidden;margin-bottom:18px;border-radius:9px;background:#0a1019}.video-link img{display:block;width:100%;max-height:270px;object-fit:cover;opacity:.75}.video-link>span{position:absolute;inset:auto 14px 13px;color:white;font-size:10px;font-weight:800}.setlist-list{list-style:none;padding:0;margin:0;display:grid}.setlist-list li{display:grid;grid-template-columns:5rem 1fr auto;gap:1rem;padding:.8rem 0;border-bottom:1px solid var(--line)}.setlist-list a{color:var(--cyan)}.setlist-list small{display:block;margin-top:4px;color:#68768b}.karaoke-numbers{line-height:1.6;white-space:nowrap}.empty-state.compact{min-height:120px}@media(max-width:800px){.archive-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.archive-row{grid-template-columns:120px 1fr}.performance-search{grid-template-columns:1fr}.floating-register{right:18px;bottom:18px}.setlist-list li{grid-template-columns:4rem 1fr}.karaoke-numbers{display:none}}@media(max-width:520px){.archive-grid{grid-template-columns:1fr}.artist-selector{grid-auto-columns:135px}}
.artist-select-card>.artist-image{position:relative;width:52px;height:52px;overflow:hidden;border-radius:50%}.artist-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.artist-image b{font:700 12px ui-monospace,monospace}.avatar-credit{display:block;margin-top:2px;color:#48566c;font-size:8px;text-align:right}
.artist-selector--grid{grid-auto-flow:row;grid-auto-columns:auto;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));overflow:visible;padding-bottom:0}.artist-selector--grid .artist-select-card{min-height:190px}.artist-selector--grid .artist-select-card>.artist-image{width:82px;height:82px}.youtube-agency-filter{margin-top:0}.youtube-artist-hero{display:grid;grid-template-columns:130px minmax(0,1fr) auto;align-items:end;gap:22px;margin-bottom:26px;padding:20px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(135deg,rgba(50,214,255,.08),rgba(255,255,255,.015))}.youtube-artist-hero>.artist-image{position:relative;display:grid;place-items:center;width:130px;height:130px;overflow:hidden;border-radius:12px;color:var(--cyan);background:rgba(50,214,255,.08);font-size:32px}.youtube-artist-hero h1{margin:5px 0 8px;font-size:28px}.youtube-artist-hero div>span{color:#718096;font:700 9px ui-monospace,monospace}@media(max-width:700px){.artist-selector--grid{grid-template-columns:repeat(2,minmax(0,1fr))}.youtube-artist-hero{grid-template-columns:88px 1fr;align-items:center}.youtube-artist-hero>.artist-image{width:88px;height:88px}.youtube-artist-hero>.button{grid-column:1/-1}}
</style>

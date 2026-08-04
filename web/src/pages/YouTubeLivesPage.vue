<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { YouTubeLiveArchive, YouTubePerformanceSearchResult } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'

const queryClient = useQueryClient()
const youtubeUrl = ref('')
const artistName = ref('')
const artistFilter = ref('')
const searchMode = ref<'artist' | 'song'>('artist')
const searchText = ref('')
const searchResults = ref<YouTubePerformanceSearchResult[]>([])
const selectedId = ref<number | null>(null)
const archives = useQuery({
  queryKey: computed(() => ['youtube-lives', artistFilter.value]),
  queryFn: () => api.youtubeLives.list(artistFilter.value || undefined),
})
const detail = useQuery({
  queryKey: computed(() => ['youtube-live', selectedId.value]),
  queryFn: () => api.youtubeLives.get(selectedId.value!),
  enabled: computed(() => selectedId.value !== null),
})
const addLive = useMutation({
  mutationFn: () => api.youtubeLives.create(youtubeUrl.value, artistName.value),
  onSuccess: async (archive) => {
    youtubeUrl.value = ''
    artistFilter.value = artistName.value
    selectedId.value = archive.id
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

function selectArchive(archive: YouTubeLiveArchive): void { selectedId.value = archive.id }
function displayDate(archive: YouTubeLiveArchive): string {
  const value = archive.broadcast_at || archive.published_at
  return value ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'long' }).format(new Date(value)) : '날짜 미확인'
}
</script>

<template>
  <div class="page">
    <PageHeader eyebrow="YOUTUBE LIVE ARCHIVE" title="우타와꾸 노래 기록" description="YouTube URL을 넣으면 방송 날짜와 댓글의 타임스탬프별 곡명을 저장합니다." />
    <section class="panel">
      <form class="performance-search" @submit.prevent="searchPerformances.mutate()">
        <select v-model="searchMode"><option value="artist">아티스트로 조회</option><option value="song">곡 제목으로 조회</option></select>
        <input v-model="searchText" required :placeholder="searchMode === 'artist' ? '예: HACHI' : '예: アポリア'" />
        <button class="button button--primary" :disabled="searchPerformances.isPending.value">전체 가창 기록 조회</button>
      </form>
      <p v-if="searchPerformances.error.value" class="form-error">{{ searchPerformances.error.value.message }}</p>
      <div v-if="searchResults.length" class="performance-results">
        <table class="data-table">
          <thead><tr><th>날짜</th><th>부른 아티스트</th><th>곡 / 원곡 가수</th><th>노래방 번호</th><th>영상</th></tr></thead>
          <tbody><tr v-for="row in searchResults" :key="row.id">
            <td>{{ row.performed_on }}</td><td><strong>{{ row.artist_name }}</strong></td>
            <td><strong>{{ row.song_title }}</strong><span>{{ row.original_artist || '원곡 가수 미상' }}</span></td>
            <td>TJ {{ row.tj_number }}<br />금영 {{ row.ky_number }}</td>
            <td><a :href="`${row.youtube_url}&t=${row.start_seconds}s`" target="_blank" rel="noreferrer" class="text-link">{{ row.timestamp_text }}</a></td>
          </tr></tbody>
        </table>
      </div>
      <div v-else-if="searchPerformances.isSuccess.value" class="empty-state"><strong>검색된 가창 기록이 없습니다</strong></div>
    </section>
    <section class="panel">
      <form class="youtube-live-form" @submit.prevent="addLive.mutate()">
        <label>아티스트 이름<input v-model="artistName" required placeholder="예: HACHI" /></label>
        <label>YouTube URL<input v-model="youtubeUrl" type="url" required placeholder="https://www.youtube.com/watch?v=..." /></label>
        <button class="button button--primary" :disabled="addLive.isPending.value">{{ addLive.isPending.value ? '댓글 확인 중…' : '셋리스트 저장' }}</button>
      </form>
      <p v-if="addLive.error.value" class="form-error">{{ addLive.error.value.message }}</p>
    </section>
    <section class="youtube-live-layout">
      <div class="panel panel--table">
        <div class="toolbar"><label>아티스트로 조회<input v-model="artistFilter" placeholder="예: HACHI" /></label><span class="count-label">{{ archives.data.value?.length || 0 }} LIVES</span></div>
        <div v-if="archives.isPending.value" class="skeleton-list"><i /><i /><i /></div>
        <div v-else-if="archives.isError.value" class="alert alert--error">기록을 불러오지 못했습니다.</div>
        <div v-else-if="!archives.data.value?.length" class="empty-state"><strong>저장된 우타와꾸가 없습니다</strong></div>
        <template v-else>
          <button v-for="archive in archives.data.value" :key="archive.id" class="youtube-live-row" :class="{ active: selectedId === archive.id }" @click="selectArchive(archive)">
            <span><strong>{{ archive.video_title || archive.artist_name }}</strong><small>{{ displayDate(archive) }}</small></span><b>{{ archive.setlist?.length || 0 }}곡</b>
          </button>
        </template>
      </div>
      <div class="panel">
        <div v-if="detail.isPending.value">셋리스트를 불러오는 중…</div>
        <div v-else-if="detail.data.value">
          <h2>{{ detail.data.value.video_title || detail.data.value.artist_name }}</h2>
          <p>{{ displayDate(detail.data.value) }} · {{ detail.data.value.performances?.length || 0 }}곡</p>
          <a :href="detail.data.value.youtube_url" target="_blank" rel="noreferrer" class="text-link">YouTube에서 열기</a>
          <ol class="setlist-list">
            <li v-for="song in detail.data.value.performances" :key="song.id">
              <a :href="`${detail.data.value.youtube_url}&t=${song.start_seconds}s`" target="_blank" rel="noreferrer">{{ song.timestamp_text }}</a>
              <span><strong>{{ song.song_title }}</strong><small>{{ song.original_artist || '원곡 가수 미상' }}</small></span>
              <span class="karaoke-numbers">TJ {{ song.tj_number }}<br />금영 {{ song.ky_number }}</span>
            </li>
          </ol>
        </div>
        <div v-else class="empty-state"><strong>왼쪽에서 방송을 선택하세요</strong></div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.performance-search,.youtube-live-form{display:flex;gap:1rem;align-items:end}.performance-search input{flex:1}.performance-results{overflow:auto;margin-top:1rem}.performance-results td span{display:block;opacity:.65;margin-top:.25rem}.youtube-live-form label{flex:1}.youtube-live-layout{display:grid;grid-template-columns:minmax(280px,.8fr) minmax(360px,1.2fr);gap:1rem}.youtube-live-row{width:100%;border:0;border-top:1px solid var(--border);background:transparent;color:inherit;padding:1rem;display:flex;justify-content:space-between;text-align:left;cursor:pointer}.youtube-live-row.active{background:rgba(34,211,238,.08)}.youtube-live-row span{display:grid;gap:.35rem}.youtube-live-row small,.setlist-list small{opacity:.65}.setlist-list{list-style:none;padding:0;margin:1.5rem 0 0;display:grid;gap:.7rem}.setlist-list li{display:grid;grid-template-columns:5rem 1fr auto;gap:1rem;padding:.8rem 0;border-bottom:1px solid var(--border)}.setlist-list a{color:#22d3ee}.karaoke-numbers{line-height:1.6;white-space:nowrap}@media(max-width:800px){.youtube-live-layout{grid-template-columns:1fr}.youtube-live-form,.performance-search{align-items:stretch;flex-direction:column}}
</style>

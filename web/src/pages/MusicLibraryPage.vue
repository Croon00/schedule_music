<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { SpotifyAlbum, SpotifyArtist } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'

const queryClient = useQueryClient()
const selectedArtistId = ref<number | null>(null)
const viewMode = ref<'grid' | 'list'>('grid')
const releaseFilter = ref<'all' | 'album' | 'single' | 'appears_on'>('all')
const selectedAlbumId = ref<string | null>(null)
const relationMode = ref(false)

const artistsQuery = useQuery({ queryKey: ['spotify-artists'], queryFn: api.spotify.artists })
const discographyQuery = useQuery({
  queryKey: ['spotify-discography', selectedArtistId],
  queryFn: () => api.spotify.discography(selectedArtistId.value as number),
  enabled: computed(() => selectedArtistId.value !== null),
})
const albumQuery = useQuery({
  queryKey: ['spotify-album', selectedAlbumId],
  queryFn: () => api.spotify.album(selectedAlbumId.value as string),
  enabled: computed(() => selectedAlbumId.value !== null),
})
const relationshipsQuery = useQuery({
  queryKey: ['spotify-relationships'],
  queryFn: api.spotify.relationships,
  enabled: relationMode,
  staleTime: 10 * 60_000,
})
const syncArtists = useMutation({
  mutationFn: api.spotify.syncArtists,
  onSuccess: (artists) => {
    queryClient.setQueryData(['spotify-artists'], artists)
  },
})

const artists = computed(() => artistsQuery.data.value ?? [])
const selectedArtist = computed(() =>
  artists.value.find((artist) => artist.local_artist_id === selectedArtistId.value),
)
const filteredAlbums = computed(() => {
  const albums = discographyQuery.data.value ?? []
  if (releaseFilter.value === 'all') return albums
  if (releaseFilter.value === 'appears_on') {
    const ownId = selectedArtist.value?.spotify_artist_id
    return albums.filter((album) => ownId && !album.artist_ids.includes(ownId))
  }
  return albums.filter((album) => album.album_type === releaseFilter.value)
})
const albumCount = computed(() =>
  (discographyQuery.data.value ?? []).filter((album) => album.album_type === 'album').length,
)
const singleCount = computed(() =>
  (discographyQuery.data.value ?? []).filter((album) => album.album_type === 'single').length,
)
const artistById = computed(() =>
  new Map(artists.value.map((artist) => [artist.local_artist_id, artist])),
)

watch(
  artists,
  (value) => {
    if (selectedArtistId.value === null) {
      selectedArtistId.value = value.find((artist) => artist.matched)?.local_artist_id ?? null
    }
  },
  { immediate: true },
)

function selectArtist(artist: SpotifyArtist): void {
  if (!artist.matched) return
  relationMode.value = false
  selectedArtistId.value = artist.local_artist_id
}

function albumKind(album: SpotifyAlbum): string {
  if (album.album_type === 'single') return album.total_tracks > 1 ? 'EP / SINGLE' : 'SINGLE'
  if (album.album_type === 'compilation') return 'COMPILATION'
  return 'ALBUM'
}

function duration(milliseconds: number | null): string {
  if (!milliseconds) return '—'
  const minutes = Math.floor(milliseconds / 60_000)
  const seconds = Math.floor((milliseconds % 60_000) / 1000)
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="page music-page">
    <PageHeader
      eyebrow="SPOTIFY CATALOG / 04"
      title="아티스트 디스코그래피"
      description="등록한 아티스트의 앨범, 싱글과 참여작을 Spotify 공식 카탈로그에서 탐색합니다."
    >
      <button
        class="button button--spotify"
        :disabled="syncArtists.isPending.value"
        @click="syncArtists.mutate()"
      >
        {{ syncArtists.isPending.value ? 'Spotify 매칭 중…' : '↻ 아티스트 동기화' }}
      </button>
    </PageHeader>

    <div v-if="artistsQuery.isError.value || syncArtists.isError.value" class="alert alert--error">
      {{ syncArtists.error.value?.message || 'Spotify 아티스트 정보를 불러오지 못했습니다.' }}
    </div>

    <section class="artist-rail-section">
      <div class="section-heading">
        <div><p class="eyebrow">SELECT ARTIST</p><h2>아티스트 선택</h2></div>
        <button class="relation-switch" :class="{ active: relationMode }" @click="relationMode = !relationMode">
          <span>⌘</span> 등록 아티스트 연관도
        </button>
      </div>
      <div v-if="artistsQuery.isPending.value" class="artist-card-rail">
        <div v-for="index in 5" :key="index" class="artist-card artist-card--loading" />
      </div>
      <div v-else class="artist-card-rail">
        <button
          v-for="artist in artists"
          :key="artist.local_artist_id"
          class="artist-card"
          :class="{ selected: artist.local_artist_id === selectedArtistId && !relationMode, unmatched: !artist.matched }"
          :disabled="!artist.matched"
          @click="selectArtist(artist)"
        >
          <img v-if="artist.image_url" :src="artist.image_url" :alt="artist.spotify_name || artist.local_name" />
          <div v-else class="artist-card__fallback">{{ artist.local_name.slice(0, 1) }}</div>
          <div class="artist-card__shade" />
          <div class="artist-card__content">
            <span>{{ artist.matched ? 'SPOTIFY ARTIST' : 'MATCH NEEDED' }}</span>
            <strong>{{ artist.spotify_name || artist.local_name }}</strong>
            <em>{{ artist.matched ? '카탈로그 보기 →' : '동기화 필요' }}</em>
          </div>
        </button>
      </div>
    </section>

    <section v-if="relationMode" class="relationship-panel">
      <div class="relationship-panel__intro">
        <p class="eyebrow">COLLABORATION MAP</p>
        <h2>등록 아티스트 연관도</h2>
        <p>공동 명의로 발매된 앨범과 싱글을 기준으로 연결 강도를 계산합니다.</p>
      </div>
      <div v-if="relationshipsQuery.isPending.value" class="relation-loading">
        Spotify 공동 크레딧을 분석하고 있습니다…
      </div>
      <div v-else-if="relationshipsQuery.data.value?.length" class="relation-grid">
        <article
          v-for="relation in relationshipsQuery.data.value"
          :key="`${relation.source_artist_id}-${relation.target_artist_id}`"
          class="relation-card"
        >
          <div class="relation-card__artists">
            <div>
              <img v-if="artistById.get(relation.source_artist_id)?.image_url" :src="artistById.get(relation.source_artist_id)?.image_url || ''" alt="" />
              <span>{{ artistById.get(relation.source_artist_id)?.spotify_name }}</span>
            </div>
            <div class="relation-card__line">
              <i v-for="index in Math.min(relation.strength, 5)" :key="index" />
              <b>{{ relation.strength }}</b>
            </div>
            <div>
              <img v-if="artistById.get(relation.target_artist_id)?.image_url" :src="artistById.get(relation.target_artist_id)?.image_url || ''" alt="" />
              <span>{{ artistById.get(relation.target_artist_id)?.spotify_name }}</span>
            </div>
          </div>
          <p>{{ relation.shared_releases.slice(0, 3).join(' · ') }}</p>
        </article>
      </div>
      <div v-else class="empty-state">
        <span>⌘</span><strong>공동 발매 연결을 찾지 못했습니다</strong>
        <p>Spotify의 Related Artists API 대신 공식 공동 크레딧만 사용하므로 결과가 없을 수 있습니다.</p>
      </div>
    </section>

    <template v-else>
      <section v-if="selectedArtist" class="artist-catalog-header">
        <div>
          <p class="eyebrow">DISCOGRAPHY</p>
          <h2>{{ selectedArtist.spotify_name || selectedArtist.local_name }}</h2>
          <div class="catalog-stats">
            <span><b>{{ albumCount }}</b> Albums</span>
            <span><b>{{ singleCount }}</b> Singles / EPs</span>
            <span><b>{{ discographyQuery.data.value?.length || 0 }}</b> Releases</span>
          </div>
        </div>
        <a v-if="selectedArtist.spotify_url" :href="selectedArtist.spotify_url" target="_blank" rel="noreferrer" class="spotify-attribution">
          Spotify에서 보기 ↗
        </a>
      </section>

      <section class="catalog-toolbar">
        <div class="filter-tabs">
          <button :class="{ active: releaseFilter === 'all' }" @click="releaseFilter = 'all'">전체</button>
          <button :class="{ active: releaseFilter === 'album' }" @click="releaseFilter = 'album'">앨범</button>
          <button :class="{ active: releaseFilter === 'single' }" @click="releaseFilter = 'single'">싱글 · EP</button>
          <button :class="{ active: releaseFilter === 'appears_on' }" @click="releaseFilter = 'appears_on'">참여작</button>
        </div>
        <div class="view-toggle" aria-label="보기 방식">
          <button :class="{ active: viewMode === 'grid' }" aria-label="이미지 보기" @click="viewMode = 'grid'">▦</button>
          <button :class="{ active: viewMode === 'list' }" aria-label="목록 보기" @click="viewMode = 'list'">☷</button>
        </div>
      </section>

      <div v-if="discographyQuery.isPending.value" class="release-grid">
        <div v-for="index in 8" :key="index" class="release-card release-card--loading" />
      </div>
      <div v-else-if="discographyQuery.isError.value" class="alert alert--error">
        {{ discographyQuery.error.value?.message || '디스코그래피 조회에 실패했습니다.' }}
      </div>
      <div v-else-if="filteredAlbums.length" :class="viewMode === 'grid' ? 'release-grid' : 'release-list'">
        <button
          v-for="album in filteredAlbums"
          :key="album.id"
          :class="viewMode === 'grid' ? 'release-card' : 'release-row'"
          @click="selectedAlbumId = album.id"
        >
          <div class="release-cover">
            <img v-if="album.image_url" :src="album.image_url" :alt="album.name" />
            <div v-else class="release-cover__fallback">♫</div>
            <div class="release-cover__action">수록곡 보기</div>
          </div>
          <div class="release-meta">
            <span>{{ albumKind(album) }} · {{ album.release_date || '날짜 미정' }}</span>
            <strong>{{ album.name }}</strong>
            <p>{{ album.artists.join(', ') }}</p>
            <em>{{ album.total_tracks }} TRACKS</em>
          </div>
        </button>
      </div>
      <div v-else class="empty-state">
        <span>♫</span><strong>표시할 발매작이 없습니다</strong><p>다른 필터를 선택하거나 Spotify 동기화를 다시 실행해 주세요.</p>
      </div>
    </template>

    <AppModal
      :open="Boolean(selectedAlbumId)"
      :title="albumQuery.data.value?.name || '앨범 불러오는 중'"
      :description="albumQuery.data.value ? `${albumQuery.data.value.artists.join(', ')} · ${albumQuery.data.value.release_date || ''}` : 'Spotify에서 수록곡을 가져오고 있습니다.'"
      @close="selectedAlbumId = null"
    >
      <div v-if="albumQuery.isPending.value" class="skeleton-list"><i /><i /><i /><i /></div>
      <div v-else-if="albumQuery.isError.value" class="alert alert--error">{{ albumQuery.error.value?.message || '앨범 조회에 실패했습니다.' }}</div>
      <div v-else-if="albumQuery.data.value" class="album-detail">
        <div class="album-detail__hero">
          <img v-if="albumQuery.data.value.image_url" :src="albumQuery.data.value.image_url" :alt="albumQuery.data.value.name" />
          <div><StatusPill :label="albumKind(albumQuery.data.value)" tone="green" /><strong>{{ albumQuery.data.value.total_tracks }}곡</strong></div>
        </div>
        <ol class="track-list">
          <li v-for="track in albumQuery.data.value.tracks" :key="track.id">
            <span>{{ track.track_number.toString().padStart(2, '0') }}</span>
            <div><strong>{{ track.name }}</strong><em>{{ track.artists.join(', ') }}</em></div>
            <b v-if="track.explicit">E</b>
            <time>{{ duration(track.duration_ms) }}</time>
            <a v-if="track.spotify_url" :href="track.spotify_url" target="_blank" rel="noreferrer" @click.stop>↗</a>
          </li>
        </ol>
        <a v-if="albumQuery.data.value.spotify_url" :href="albumQuery.data.value.spotify_url" target="_blank" rel="noreferrer" class="button button--spotify album-detail__link">Spotify에서 전체 보기 ↗</a>
      </div>
    </AppModal>
  </div>
</template>

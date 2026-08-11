<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { SpotifyAlbum } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const artistId = computed(() => Number(route.params.artistId))
const selectedAlbumId = ref<string | null>(null)
const releaseFilter = ref<'all' | 'album' | 'single' | 'appears_on'>('all')

const artistsQuery = useQuery({ queryKey: ['spotify-artists'], queryFn: api.spotify.artists })
const artist = computed(() =>
  (artistsQuery.data.value ?? []).find((item) => item.local_artist_id === artistId.value),
)
const discographyQuery = useQuery({
  queryKey: ['spotify-discography', artistId],
  queryFn: () => api.spotify.discography(artistId.value),
  enabled: computed(() => Boolean(artist.value?.matched)),
})
const albumQuery = useQuery({
  queryKey: ['spotify-album', selectedAlbumId],
  queryFn: () => api.spotify.album(selectedAlbumId.value as string),
  enabled: computed(() => selectedAlbumId.value !== null),
})
const filteredAlbums = computed(() => {
  const albums = discographyQuery.data.value ?? []
  if (releaseFilter.value === 'all') return albums
  if (releaseFilter.value === 'appears_on') {
    return albums.filter((album) => artist.value?.spotify_artist_id && !album.artist_ids.includes(artist.value.spotify_artist_id))
  }
  return albums.filter((album) => album.album_type === releaseFilter.value)
})
const excludeArtist = useMutation({
  mutationFn: api.spotify.excludeArtist,
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['spotify-artists'] })
    router.push('/music')
  },
})

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

function confirmExclusion(): void {
  if (!artist.value) return
  if (window.confirm(`${artist.value.spotify_name || artist.value.local_name}의 Spotify 연결을 제거할까요? X 계정은 유지됩니다.`)) {
    excludeArtist.mutate(artist.value.local_artist_id)
  }
}
</script>

<template>
  <div class="page music-page artist-detail-page">
    <PageHeader eyebrow="ARTIST CATALOG" title="아티스트 디스코그래피" description="아티스트 프로필과 Spotify 공식 발매작을 확인합니다.">
      <RouterLink to="/music" class="button button--ghost">← 아티스트 목록</RouterLink>
    </PageHeader>

    <div v-if="artistsQuery.isPending.value" class="skeleton-list"><i /><i /><i /></div>
    <div v-else-if="!artist" class="empty-state"><strong>아티스트를 찾을 수 없습니다</strong><RouterLink to="/music">목록으로 돌아가기</RouterLink></div>
    <template v-else>
      <section class="artist-profile-hero">
        <img v-if="artist.image_url" :src="artist.image_url" :alt="artist.spotify_name || artist.local_name" />
        <div v-else class="artist-profile-hero__fallback">{{ artist.local_name.slice(0, 1) }}</div>
        <div class="artist-profile-hero__info">
          <p class="eyebrow">{{ artist.agency || (artist.artist_kind === 'vtuber' ? 'VTUBER' : 'SINGER') }}</p>
          <h1>{{ artist.spotify_name || artist.local_name }}</h1>
          <span>{{ artist.artist_kind === 'vtuber' ? 'Virtual Artist' : 'Music Artist' }}</span>
          <a v-if="artist.spotify_url" :href="artist.spotify_url" target="_blank" rel="noreferrer" class="spotify-attribution">Spotify에서 확인 ↗</a>
        </div>
        <UButton class="button button--danger" :disabled="excludeArtist.isPending.value" @click="confirmExclusion">Spotify 연결 제거</UButton>
      </section>

      <section class="catalog-toolbar">
        <div class="filter-tabs">
          <UButton :class="{ active: releaseFilter === 'all' }" @click="releaseFilter = 'all'">전체</UButton>
          <UButton :class="{ active: releaseFilter === 'album' }" @click="releaseFilter = 'album'">앨범</UButton>
          <UButton :class="{ active: releaseFilter === 'single' }" @click="releaseFilter = 'single'">싱글 · EP</UButton>
          <UButton :class="{ active: releaseFilter === 'appears_on' }" @click="releaseFilter = 'appears_on'">참여작</UButton>
        </div>
        <span class="count-label">{{ filteredAlbums.length }} RELEASES</span>
      </section>

      <div v-if="discographyQuery.isPending.value" class="release-grid"><div v-for="n in 8" :key="n" class="release-card release-card--loading" /></div>
      <div v-else-if="discographyQuery.isError.value" class="alert alert--error">{{ discographyQuery.error.value?.message || '디스코그래피 조회에 실패했습니다.' }}</div>
      <div v-else-if="filteredAlbums.length" class="release-grid">
        <UButton v-for="album in filteredAlbums" :key="album.id" class="release-card" @click="selectedAlbumId = album.id">
          <div class="release-card__cover"><img v-if="album.image_url" :src="album.image_url" :alt="album.name" /><span v-else>♫</span><StatusPill :label="albumKind(album)" tone="green" /></div>
          <div class="release-card__body"><time>{{ album.release_date || '발매일 미상' }}</time><strong>{{ album.name }}</strong><p>{{ album.artists.join(', ') }}</p><span>{{ album.total_tracks }}곡</span></div>
        </UButton>
      </div>
      <div v-else class="empty-state"><strong>표시할 발매작이 없습니다</strong></div>
    </template>

    <AppModal :open="Boolean(selectedAlbumId)" :title="albumQuery.data.value?.name || '앨범 불러오는 중'" :description="albumQuery.data.value ? `${albumQuery.data.value.artists.join(', ')} · ${albumQuery.data.value.release_date || ''}` : 'Spotify에서 수록곡을 가져오고 있습니다.'" @close="selectedAlbumId = null">
      <div v-if="albumQuery.isPending.value" class="skeleton-list"><i /><i /><i /></div>
      <div v-else-if="albumQuery.data.value" class="album-detail">
        <div class="album-detail__hero"><img v-if="albumQuery.data.value.image_url" :src="albumQuery.data.value.image_url" :alt="albumQuery.data.value.name" /><strong>{{ albumQuery.data.value.total_tracks }}곡</strong></div>
        <ol class="track-list"><li v-for="track in albumQuery.data.value.tracks" :key="track.id"><span>{{ track.track_number.toString().padStart(2, '0') }}</span><div><strong>{{ track.name }}</strong><em>{{ track.artists.join(', ') }}</em></div><b v-if="track.explicit">E</b><time>{{ duration(track.duration_ms) }}</time><a v-if="track.spotify_url" :href="track.spotify_url" target="_blank" rel="noreferrer">↗</a></li></ol>
      </div>
    </AppModal>
  </div>
</template>

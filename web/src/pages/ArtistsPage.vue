<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { Artist, SourceType } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'

const queryClient = useQueryClient()
const artistsQuery = useQuery({ queryKey: ['artists'], queryFn: api.artists.list })
const artistModal = ref(false)
const sourceArtist = ref<Artist | null>(null)
const feedback = ref('')
const artistForm = reactive({ name: '', display_name: '', x_username: '', notes: '' })
const sourceForm = reactive({
  source_type: 'x' as SourceType,
  label: '',
  value: '',
  is_active: true,
})

const refresh = () => queryClient.invalidateQueries({ queryKey: ['artists'] })
const createArtist = useMutation({
  mutationFn: api.artists.create,
  onSuccess: async () => {
    await refresh()
    artistModal.value = false
    Object.assign(artistForm, { name: '', display_name: '', x_username: '', notes: '' })
    feedback.value = '아티스트를 등록했습니다.'
  },
})
const addSource = useMutation({
  mutationFn: ({ artistId }: { artistId: number }) => api.artists.addSource(artistId, sourceForm),
  onSuccess: async () => {
    await refresh()
    sourceArtist.value = null
    Object.assign(sourceForm, { source_type: 'x', label: '', value: '', is_active: true })
    feedback.value = '수집 소스를 추가했습니다.'
  },
})
const removeArtist = useMutation({
  mutationFn: api.artists.remove,
  onSuccess: refresh,
})
const removeSource = useMutation({
  mutationFn: ({ artistId, sourceId }: { artistId: number; sourceId: number }) =>
    api.artists.removeSource(artistId, sourceId),
  onSuccess: refresh,
})

function submitArtist(): void {
  createArtist.mutate({
    name: artistForm.name,
    display_name: artistForm.display_name || undefined,
    x_username: artistForm.x_username || undefined,
    notes: artistForm.notes || undefined,
  })
}

function confirmArtistDelete(artist: Artist): void {
  if (window.confirm(`${artist.display_name || artist.name}과 연결된 소스를 모두 삭제할까요?`)) {
    removeArtist.mutate(artist.id)
  }
}

function sourceLabel(type: SourceType): string {
  return { x: 'X', official_site: '공식 사이트', ticket_site: '티켓', rss: 'RSS', other: '기타' }[type]
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="SOURCE REGISTRY / 02"
      title="아티스트와 공식 소스"
      description="신뢰할 수 있는 출처만 등록해 수집 범위를 선명하게 관리합니다."
    >
      <button class="button button--primary" @click="artistModal = true">+ 새 아티스트</button>
    </PageHeader>

    <div v-if="feedback" class="alert alert--success" @click="feedback = ''">{{ feedback }}</div>
    <div v-if="artistsQuery.isError.value" class="alert alert--error">
      목록을 불러오지 못했습니다. FastAPI 연결을 확인해 주세요.
    </div>

    <section class="panel panel--table">
      <div class="panel__heading">
        <div>
          <p class="eyebrow">MONITORED ARTISTS</p>
          <h2>등록 목록</h2>
        </div>
        <span class="count-label">{{ artistsQuery.data.value?.length || 0 }} ARTISTS</span>
      </div>
      <div v-if="artistsQuery.isPending.value" class="skeleton-list"><i /><i /><i /></div>
      <div v-else-if="artistsQuery.data.value?.length" class="artist-list">
        <article v-for="artist in artistsQuery.data.value" :key="artist.id" class="artist-row">
          <div class="artist-avatar">{{ (artist.display_name || artist.name).slice(0, 1) }}</div>
          <div class="artist-row__identity">
            <strong>{{ artist.display_name || artist.name }}</strong>
            <span>{{ artist.name }} · ID {{ artist.id }}</span>
            <p v-if="artist.notes">{{ artist.notes }}</p>
          </div>
          <div class="source-tags">
            <span v-for="source in artist.sources" :key="source.id" class="source-tag">
              <b>{{ sourceLabel(source.source_type) }}</b>
              {{ source.label || source.value }}
              <button
                :aria-label="`${source.label || source.value} 삭제`"
                @click="removeSource.mutate({ artistId: artist.id, sourceId: source.id })"
              >
                ×
              </button>
            </span>
            <span v-if="!artist.sources.length" class="muted">연결된 소스 없음</span>
          </div>
          <StatusPill
            :label="artist.sources.some((source) => source.is_active) ? '수집 중' : '대기'"
            :tone="artist.sources.some((source) => source.is_active) ? 'green' : 'muted'"
          />
          <div class="row-actions">
            <button class="button button--ghost" @click="sourceArtist = artist">소스 추가</button>
            <button class="icon-button icon-button--danger" @click="confirmArtistDelete(artist)">×</button>
          </div>
        </article>
      </div>
      <div v-else class="empty-state">
        <span>◉</span><strong>첫 아티스트를 등록해 보세요</strong>
        <p>X 계정이나 공식 사이트를 함께 등록하면 수집 준비가 끝납니다.</p>
      </div>
    </section>

    <AppModal
      :open="artistModal"
      title="새 아티스트 등록"
      description="표시 이름과 첫 X 계정을 한 번에 등록할 수 있습니다."
      @close="artistModal = false"
    >
      <form class="form-grid" @submit.prevent="submitArtist">
        <label>기준 이름<input v-model="artistForm.name" required maxlength="120" placeholder="예: HACHI" /></label>
        <label>표시 이름<input v-model="artistForm.display_name" maxlength="120" placeholder="예: HACHI / ハチ" /></label>
        <label class="form-grid__wide">X 사용자명<input v-model="artistForm.x_username" placeholder="@HACHI_08" /></label>
        <label class="form-grid__wide">메모<textarea v-model="artistForm.notes" rows="3" placeholder="레이블, 활동 그룹 등 운영 메모" /></label>
        <p v-if="createArtist.error.value" class="form-error">{{ createArtist.error.value.message }}</p>
        <div class="form-actions">
          <button type="button" class="button button--ghost" @click="artistModal = false">취소</button>
          <button class="button button--primary" :disabled="createArtist.isPending.value">
            {{ createArtist.isPending.value ? '등록 중…' : '등록하기' }}
          </button>
        </div>
      </form>
    </AppModal>

    <AppModal
      :open="Boolean(sourceArtist)"
      :title="`${sourceArtist?.display_name || sourceArtist?.name || ''} 소스 추가`"
      description="공식 계정과 공개 페이지만 등록해 주세요."
      @close="sourceArtist = null"
    >
      <form class="form-grid" @submit.prevent="sourceArtist && addSource.mutate({ artistId: sourceArtist.id })">
        <label>
          소스 종류
          <select v-model="sourceForm.source_type">
            <option value="x">X 계정</option><option value="official_site">공식 사이트</option>
            <option value="ticket_site">티켓 사이트</option><option value="rss">RSS</option><option value="other">기타</option>
          </select>
        </label>
        <label>표시 이름<input v-model="sourceForm.label" placeholder="Official news" /></label>
        <label class="form-grid__wide">URL 또는 사용자명<input v-model="sourceForm.value" required maxlength="500" /></label>
        <label class="check-label"><input v-model="sourceForm.is_active" type="checkbox" /> 즉시 수집 활성화</label>
        <p v-if="addSource.error.value" class="form-error">{{ addSource.error.value.message }}</p>
        <div class="form-actions">
          <button type="button" class="button button--ghost" @click="sourceArtist = null">취소</button>
          <button class="button button--primary" :disabled="addSource.isPending.value">소스 추가</button>
        </div>
      </form>
    </AppModal>
  </div>
</template>

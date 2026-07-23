<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { CandidateStatus } from '@/api/types'
import AppModal from '@/components/AppModal.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'

const queryClient = useQueryClient()
const filter = ref<CandidateStatus | ''>('')
const modalOpen = ref(false)
const artistsQuery = useQuery({ queryKey: ['artists'], queryFn: api.artists.list })
const eventsQuery = useQuery({
  queryKey: ['events', filter],
  queryFn: () => api.events.list(filter.value || undefined),
})
const form = reactive({
  artist_id: '',
  title: '',
  starts_at: '',
  venue: '',
  ticket_opens_at: '',
  ticket_closes_at: '',
  ticket_url: '',
  source_url: '',
  price_text: '',
  raw_text: '',
  status: 'needs_review' as CandidateStatus,
})

const artistMap = computed(() => new Map((artistsQuery.data.value ?? []).map((artist) => [artist.id, artist.display_name || artist.name])))
const createEvent = useMutation({
  mutationFn: api.events.create,
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['events'] })
    modalOpen.value = false
    Object.assign(form, { artist_id: '', title: '', starts_at: '', venue: '', ticket_opens_at: '', ticket_closes_at: '', ticket_url: '', source_url: '', price_text: '', raw_text: '', status: 'needs_review' })
  },
})

function optional(value: string): string | null {
  return value || null
}

function submit(): void {
  createEvent.mutate({
    artist_id: form.artist_id ? Number(form.artist_id) : null,
    source_id: null,
    title: form.title,
    starts_at: optional(form.starts_at),
    venue: optional(form.venue),
    ticket_opens_at: optional(form.ticket_opens_at),
    ticket_closes_at: optional(form.ticket_closes_at),
    ticket_url: optional(form.ticket_url),
    source_url: optional(form.source_url),
    price_text: optional(form.price_text),
    raw_text: optional(form.raw_text),
    status: form.status,
  })
}

function displayDate(value: string | null): string {
  if (!value) return '미정'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const tones: Record<CandidateStatus, 'amber' | 'cyan' | 'green' | 'muted'> = {
  needs_review: 'amber', ready: 'cyan', synced: 'green', ignored: 'muted',
}
const labels: Record<CandidateStatus, string> = {
  needs_review: '검토 필요', ready: '준비 완료', synced: '동기화됨', ignored: '무시됨',
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="EVENT CANDIDATES / 03"
      title="일정 후보"
      description="AI가 추출했거나 직접 등록한 공연·티켓 일정을 검토합니다."
    >
      <button class="button button--primary" @click="modalOpen = true">+ 일정 후보 등록</button>
    </PageHeader>

    <section class="panel panel--table">
      <div class="toolbar">
        <div class="filter-tabs">
          <button :class="{ active: filter === '' }" @click="filter = ''">전체</button>
          <button :class="{ active: filter === 'needs_review' }" @click="filter = 'needs_review'">검토 필요</button>
          <button :class="{ active: filter === 'ready' }" @click="filter = 'ready'">준비 완료</button>
          <button :class="{ active: filter === 'synced' }" @click="filter = 'synced'">동기화됨</button>
        </div>
        <span class="count-label">{{ eventsQuery.data.value?.length || 0 }} EVENTS</span>
      </div>

      <div v-if="eventsQuery.isPending.value" class="skeleton-list"><i /><i /><i /></div>
      <div v-else-if="eventsQuery.isError.value" class="alert alert--error">일정 후보를 불러오지 못했습니다.</div>
      <div v-else-if="eventsQuery.data.value?.length" class="event-table-wrap">
        <table class="data-table">
          <thead><tr><th>일정</th><th>아티스트</th><th>시작</th><th>티켓 마감</th><th>상태</th><th>링크</th></tr></thead>
          <tbody>
            <tr v-for="event in eventsQuery.data.value" :key="event.id">
              <td><strong>{{ event.title }}</strong><span>{{ event.venue || '장소 미정' }}</span></td>
              <td>{{ event.artist_id ? artistMap.get(event.artist_id) || `ID ${event.artist_id}` : '미지정' }}</td>
              <td>{{ displayDate(event.starts_at) }}</td>
              <td>{{ displayDate(event.ticket_closes_at) }}</td>
              <td><StatusPill :label="labels[event.status]" :tone="tones[event.status]" /></td>
              <td><a v-if="event.source_url || event.ticket_url" :href="event.ticket_url || event.source_url || '#'" target="_blank" rel="noreferrer" class="text-link">원문 ↗</a><span v-else>—</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state"><span>◇</span><strong>조건에 맞는 일정이 없습니다</strong><p>새 후보를 직접 등록하거나 필터를 바꿔 보세요.</p></div>
    </section>

    <AppModal :open="modalOpen" title="일정 후보 등록" description="불확실한 정보는 비워 두고 검토 상태로 저장할 수 있습니다." @close="modalOpen = false">
      <form class="form-grid" @submit.prevent="submit">
        <label>제목<input v-model="form.title" required maxlength="200" placeholder="HACHI 2nd LIVE" /></label>
        <label>아티스트<select v-model="form.artist_id"><option value="">미지정</option><option v-for="artist in artistsQuery.data.value" :key="artist.id" :value="artist.id">{{ artist.display_name || artist.name }}</option></select></label>
        <label>시작 일시<input v-model="form.starts_at" type="datetime-local" /></label>
        <label>장소<input v-model="form.venue" /></label>
        <label>티켓 오픈<input v-model="form.ticket_opens_at" type="datetime-local" /></label>
        <label>티켓 마감<input v-model="form.ticket_closes_at" type="datetime-local" /></label>
        <label class="form-grid__wide">티켓 URL<input v-model="form.ticket_url" type="url" /></label>
        <label class="form-grid__wide">원문 URL<input v-model="form.source_url" type="url" /></label>
        <label>가격 정보<input v-model="form.price_text" placeholder="¥7,500" /></label>
        <label>상태<select v-model="form.status"><option value="needs_review">검토 필요</option><option value="ready">준비 완료</option><option value="synced">동기화됨</option><option value="ignored">무시됨</option></select></label>
        <label class="form-grid__wide">원문 메모<textarea v-model="form.raw_text" rows="3" /></label>
        <p v-if="createEvent.error.value" class="form-error">{{ createEvent.error.value.message }}</p>
        <div class="form-actions"><button type="button" class="button button--ghost" @click="modalOpen = false">취소</button><button class="button button--primary" :disabled="createEvent.isPending.value">후보 저장</button></div>
      </form>
    </AppModal>
  </div>
</template>

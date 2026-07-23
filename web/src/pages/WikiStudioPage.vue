<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { SongArticleInput } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'

const queryClient = useQueryClient()
const templatesQuery = useQuery({ queryKey: ['wiki-templates'], queryFn: api.namuwiki.templates })
const selectedTemplate = ref('')
const instruction = ref('')
const output = ref('')
const copied = ref(false)
const templateForm = reactive({ template_id: '', name: '', description: '', template_example: '' })
const song = reactive({
  title: '', artist: '', release_date: '', album: '', album_type: '싱글',
  lyricist: '', composer: '', arranger: '', intro: '', youtube_url: '', categories: '',
  lyricsText: '',
})

function payload(): SongArticleInput {
  return {
    title: song.title,
    artist: song.artist,
    release_date: song.release_date || undefined,
    album: song.album || undefined,
    album_type: song.album_type || undefined,
    lyricist: song.lyricist || undefined,
    composer: song.composer || undefined,
    arranger: song.arranger || undefined,
    intro: song.intro || undefined,
    youtube_url: song.youtube_url || undefined,
    categories: song.categories.split(',').map((item) => item.trim()).filter(Boolean),
    lyrics: song.lyricsText.split('\n').filter((line) => line.trim()).map((line) => ({ original: line })),
  }
}

const renderArticle = useMutation({
  mutationFn: () => selectedTemplate.value
    ? api.namuwiki.renderWithSavedTemplate(selectedTemplate.value, payload(), instruction.value)
    : api.namuwiki.render(payload()),
  onSuccess: (result) => { output.value = result.text },
})
const saveTemplate = useMutation({
  mutationFn: () => api.namuwiki.saveTemplate(templateForm),
  onSuccess: async (result) => {
    await queryClient.invalidateQueries({ queryKey: ['wiki-templates'] })
    selectedTemplate.value = result.template_id
  },
})

async function copyOutput(): Promise<void> {
  await navigator.clipboard.writeText(output.value)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1500)
}
</script>

<template>
  <div class="page">
    <PageHeader eyebrow="WIKI STUDIO / 04" title="나무위키 문서 스튜디오" description="곡 정보를 구조화해 기본 문서 또는 저장한 예시 기반 문서를 생성합니다." />
    <div class="studio-grid">
      <section class="panel">
        <div class="panel__heading"><div><p class="eyebrow">SONG DATA</p><h2>곡 정보</h2></div><span class="count-label">INPUT</span></div>
        <form class="form-grid" @submit.prevent="renderArticle.mutate()">
          <label>곡명<input v-model="song.title" required /></label><label>아티스트<input v-model="song.artist" required /></label>
          <label>발매일<input v-model="song.release_date" placeholder="2026-08-12" /></label><label>앨범<input v-model="song.album" /></label>
          <label>작사<input v-model="song.lyricist" /></label><label>작곡<input v-model="song.composer" /></label>
          <label>편곡<input v-model="song.arranger" /></label><label>YouTube URL<input v-model="song.youtube_url" type="url" /></label>
          <label class="form-grid__wide">분류 (쉼표 구분)<input v-model="song.categories" placeholder="일본 음악, 버추얼 유튜버 오리지널 곡" /></label>
          <label class="form-grid__wide">한 줄 소개<textarea v-model="song.intro" rows="2" /></label>
          <label class="form-grid__wide">가사 원문<textarea v-model="song.lyricsText" rows="7" placeholder="한 줄에 한 소절씩 입력" /></label>
          <label class="form-grid__wide">저장 템플릿<select v-model="selectedTemplate"><option value="">기본 렌더러</option><option v-for="template in templatesQuery.data.value" :key="template.template_id" :value="template.template_id">{{ template.name }}</option></select></label>
          <label v-if="selectedTemplate" class="form-grid__wide">AI 추가 지시<input v-model="instruction" maxlength="1000" placeholder="표 구성은 유지하고 개요를 간결하게" /></label>
          <p v-if="renderArticle.error.value" class="form-error">{{ renderArticle.error.value.message }}</p>
          <div class="form-actions"><button class="button button--primary" :disabled="renderArticle.isPending.value">{{ renderArticle.isPending.value ? '생성 중…' : selectedTemplate ? '템플릿으로 생성' : '문서 생성' }}</button></div>
        </form>
      </section>

      <section class="panel output-panel">
        <div class="panel__heading"><div><p class="eyebrow">RENDERED WIKITEXT</p><h2>생성 결과</h2></div><button v-if="output" class="button button--ghost" @click="copyOutput">{{ copied ? '복사됨 ✓' : '복사' }}</button></div>
        <pre v-if="output" class="wiki-output">{{ output }}</pre>
        <div v-else class="empty-state"><span>✦</span><strong>문서가 이곳에 생성됩니다</strong><p>입력값은 HTML로 렌더링하지 않고 안전한 텍스트로 보여줍니다.</p></div>
      </section>
    </div>

    <details class="panel template-builder">
      <summary><span><b>재사용 템플릿 등록</b><small>기존 나무위키 문서 예시를 저장해 AI 렌더링에 사용합니다.</small></span><span>＋</span></summary>
      <form class="form-grid" @submit.prevent="saveTemplate.mutate()">
        <label>템플릿 ID<input v-model="templateForm.template_id" required pattern="[A-Za-z0-9_-]+" placeholder="hachi-song" /></label>
        <label>이름<input v-model="templateForm.name" required placeholder="HACHI 곡 문서" /></label>
        <label class="form-grid__wide">설명<input v-model="templateForm.description" /></label>
        <label class="form-grid__wide">문서 예시<textarea v-model="templateForm.template_example" required rows="10" /></label>
        <p v-if="saveTemplate.error.value" class="form-error">{{ saveTemplate.error.value.message }}</p>
        <div class="form-actions"><button class="button button--primary" :disabled="saveTemplate.isPending.value">템플릿 저장</button></div>
      </form>
    </details>
  </div>
</template>

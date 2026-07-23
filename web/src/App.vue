<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })

const navigation = [
  { to: '/', label: '대시보드', icon: '⌁' },
  { to: '/artists', label: '아티스트 · 소스', icon: '◉' },
  { to: '/events', label: '일정 후보', icon: '◇' },
  { to: '/music', label: 'Spotify 음악', icon: '♫' },
  { to: '/wiki', label: 'Wiki Studio', icon: '✦' },
  { to: '/settings', label: '연동 설정', icon: '⚙' },
]
</script>

<template>
  <UApp>
    <div class="app-shell">
      <button class="mobile-menu" aria-label="메뉴 열기" @click="ui.toggleSidebar">☰</button>
      <div v-if="ui.sidebarOpen" class="sidebar-scrim" @click="ui.closeSidebar" />
      <aside class="sidebar" :class="{ 'sidebar--open': ui.sidebarOpen }">
        <div class="brand">
          <div class="brand__mark">S</div>
          <div>
            <strong>SCHEDULE MUSIC</strong>
            <span>OPERATIONS CONSOLE</span>
          </div>
        </div>

        <nav aria-label="주요 메뉴">
          <RouterLink
            v-for="item in navigation"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            @click="ui.closeSidebar"
          >
            <span class="nav-link__icon">{{ item.icon }}</span>
            {{ item.label }}
          </RouterLink>
        </nav>

        <div class="sidebar__bottom">
          <div class="connection-card">
            <span class="connection-card__pulse" :class="{ offline: health.isError.value }" />
            <div>
              <strong>{{ health.isError.value ? 'API 연결 끊김' : '시스템 정상' }}</strong>
              <span>{{ health.isFetching.value ? '상태 확인 중' : 'FastAPI 연결 상태' }}</span>
            </div>
          </div>
          <p>Asia/Seoul · JST 일정 보존</p>
        </div>
      </aside>

      <main class="main-content">
        <RouterView />
      </main>
    </div>
  </UApp>
</template>

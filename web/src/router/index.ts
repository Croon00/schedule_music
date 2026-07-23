import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/pages/DashboardPage.vue') },
    { path: '/artists', name: 'artists', component: () => import('@/pages/ArtistsPage.vue') },
    { path: '/events', name: 'events', component: () => import('@/pages/EventsPage.vue') },
    { path: '/music', name: 'music', component: () => import('@/pages/MusicLibraryPage.vue') },
    { path: '/wiki', name: 'wiki', component: () => import('@/pages/WikiStudioPage.vue') },
    { path: '/settings', name: 'settings', component: () => import('@/pages/SettingsPage.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

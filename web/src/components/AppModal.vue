<script setup lang="ts">
defineProps<{ open: boolean; title: string; description?: string }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <section class="modal" role="dialog" aria-modal="true" :aria-label="title">
        <header class="modal__header">
          <div>
            <h2>{{ title }}</h2>
            <p v-if="description">{{ description }}</p>
          </div>
          <button class="icon-button" aria-label="닫기" @click="emit('close')">×</button>
        </header>
        <slot />
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{ open: boolean; title: string; description?: string }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <UModal
    :open="open"
    :title="title"
    :description="description"
    :ui="{ content: 'modal' }"
    @update:open="(value: boolean) => !value && emit('close')"
  >
    <template #body>
      <slot />
    </template>
  </UModal>
</template>

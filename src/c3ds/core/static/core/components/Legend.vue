<script setup lang="ts">
interface Track {
  name?: string;
  color?: string;
}

defineProps<{
  tracks?: {[k: string]: Track}
}>()
</script>

<template>
  <div class="legend-container">
    <div class="legend flex flex-wrap flex-shrink-0">
      <div v-for="(track, slug) in tracks" :key="slug" class="track text-3xl" :style="{borderColor: track.color}">
        <p>{{ track.name }}</p>
      </div>
    </div>
  </div>
</template>

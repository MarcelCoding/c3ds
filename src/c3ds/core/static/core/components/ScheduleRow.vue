<script setup lang="ts">
  import {ProcessedEvent} from "../ts/schedule_types.ts";
  import {computed, ComputedRef, onMounted, ref} from "vue";
  import {getCurrentTime} from "../ts/ntp.ts";

  const props = defineProps<{
    talk: ProcessedEvent
  }>()

  const now = ref(getCurrentTime())
  const duration_seconds: number = props.talk.moment_duration.asSeconds()

  const percent_completed: ComputedRef<number> = computed(() => {
    if (props.talk.date_start.isAfter(now.value)) {
      return  0
    } else {
      return now.value.diff(props.talk.date_start, 's', true) / duration_seconds * 100
    }
  })

  function clock_tick() {
    now.value = getCurrentTime()
  }
  let lastClockTick: number|undefined = undefined
  function animation_callback(timestamp: number) {
    // limit the clock tick to 10 FPS
    if (lastClockTick === undefined || (timestamp - lastClockTick) > 100) {
      clock_tick()
      lastClockTick = timestamp
    }
    window.requestAnimationFrame(animation_callback)
  }
  onMounted(() => {
    window.requestAnimationFrame(animation_callback)
  })
</script>

<template>
  <div class="schedule-row w-full grid grid-cols-schedule text-4xl gap-2">
    <div class="time font-numbers text-5xl pr-1">{{ props.talk.start }}</div>
    <div class="marker" :style="{backgroundColor: props.talk.color}">&nbsp;</div>
    <div class="talk pl-2 pr-1" :style="{background: `linear-gradient(90deg, var(--color-progress) ${percent_completed}%, rgba(0,0,0,0) ${percent_completed}%)`}">
      <h2 class="title text-5xl">{{ props.talk.title }}</h2>
      <p class="meta">in {{ props.talk.room }}
        <template v-if="props.talk.speakers.length > 0">mit {{ props.talk.speakers.join(', ') }}</template>
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Datenspuren 2026: hard edges, hairline rules between the entries */
.schedule-row {
  /* items stretch, so the track colour bar spans the whole row */
  padding-bottom: 0.35rem;
  margin-bottom: 0.35rem;
  border-bottom: 1px solid var(--color-line-soft);
}

.time {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1.05;
  color: var(--color-fg);
}

.marker {
  /* talks without a track keep the accent colour instead of a gap */
  background-color: var(--color-accent);
}

.title {
  font-weight: 700;
  line-height: 1.05;
  color: var(--color-fg);
}

.meta {
  color: var(--color-muted);
  line-height: 1.15;
}
</style>

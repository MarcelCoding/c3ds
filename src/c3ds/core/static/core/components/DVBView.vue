<script setup lang="ts">
import {onMounted, onBeforeUnmount, nextTick, ref, computed} from "vue";
import DVBStopBoard from "./DVBStopBoard.vue";

interface Departure {
  line: string
  direction: string
  scheduled: string
  real_time: string | null
  state: string
  platform: string | null
  mode: string
}

interface StopDepartures {
  stop_name: string
  departures: Departure[]
  error?: boolean
}

interface DVBData {
  stops: StopDepartures[]
}

const props = defineProps<{
  dvbData: DVBData | null
}>()

const visible = ref(false)
const boardEl = ref<HTMLElement | null>(null)
const now = ref(Date.now())

const MIN_FONT_SIZE = 6
const MAX_FONT_SIZE = 20

let fitFrame = 0
let resizeObserver: ResizeObserver | null = null
let tickInterval = 0

function fits(el: HTMLElement) {
  return el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1
}

function fitToContainer() {
  const el = boardEl.value
  if (!el || !el.clientHeight) return

  let low = MIN_FONT_SIZE
  let high = MAX_FONT_SIZE
  let best = MIN_FONT_SIZE
  for (let i = 0; i < 14; i++) {
    const mid = (low + high) / 2
    el.style.fontSize = `${mid}px`
    if (fits(el)) {
      best = mid
      low = mid
    } else {
      high = mid
    }
  }
  el.style.fontSize = `${best}px`
}

function scheduleFit() {
  cancelAnimationFrame(fitFrame)
  fitFrame = requestAnimationFrame(fitToContainer)
}

// Split into two explicit reading-order columns rather than relying on CSS multi-column
// balancing - that gives no way to target "last stop in its column" to drop its trailing divider.
const leftStops = computed(() => {
  const stops = props.dvbData?.stops ?? []
  return stops.slice(0, Math.ceil(stops.length / 2))
})
const rightStops = computed(() => {
  const stops = props.dvbData?.stops ?? []
  return stops.slice(Math.ceil(stops.length / 2))
})

onMounted(async () => {
  visible.value = true
  tickInterval = window.setInterval(() => {
    now.value = Date.now()
  }, 15000)

  await nextTick()
  if (boardEl.value) {
    resizeObserver = new ResizeObserver(scheduleFit)
    resizeObserver.observe(boardEl.value)
  }
  await document.fonts?.ready
  scheduleFit()
})

onBeforeUnmount(() => {
  cancelAnimationFrame(fitFrame)
  clearInterval(tickInterval)
  resizeObserver?.disconnect()
})
</script>

<template>
  <div v-show="visible && dvbData" ref="boardEl" class="dvb-board">
    <div class="dvb-column">
      <DVBStopBoard v-for="stop in leftStops" :key="stop.stop_name" :stop="stop" :now="now"/>
    </div>
    <div class="dvb-column">
      <DVBStopBoard v-for="stop in rightStops" :key="stop.stop_name" :stop="stop" :now="now"/>
    </div>
  </div>
</template>

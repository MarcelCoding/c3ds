<script setup lang="ts">
import {onMounted, onBeforeUnmount, nextTick, ref} from "vue";

interface HourlyReading {
  timestamp: string
  temperature: number | null
  icon: string | null
  precipitation: number | null
}

interface DailyReading {
  date: string
  temp_min: number
  temp_max: number
  precipitation: number
  icon: string | null
}

interface WeatherData {
  hourly: HourlyReading[]
  daily: DailyReading[]
}

defineProps<{
  weatherData: WeatherData | null
}>()

const visible = ref(false)
const forecastEl = ref<HTMLElement | null>(null)

const MIN_FONT_SIZE = 6
const MAX_FONT_SIZE = 20

let fitFrame = 0
let resizeObserver: ResizeObserver | null = null

function fits(el: HTMLElement) {
  return el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1
}

function fitToContainer() {
  const el = forecastEl.value
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

// Bright Sky's icon enum (shared with the old Dark Sky API it grew out of).
const ICONS: Record<string, string> = {
  'clear-day': '☀️',
  'clear-night': '🌙',
  'partly-cloudy-day': '⛅',
  'partly-cloudy-night': '🌥️',
  'cloudy': '☁️',
  'fog': '🌫️',
  'wind': '💨',
  'rain': '🌧️',
  'sleet': '🌨️',
  'snow': '❄️',
  'hail': '🧊',
  'thunderstorm': '⛈️',
}

function iconFor(icon: string | null): string {
  return (icon && ICONS[icon]) || '🌡️'
}

function hourLabel(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString('de-DE', {hour: '2-digit', minute: '2-digit'})
}

function dayLabel(date: string): string {
  // A plain "YYYY-MM-DD" is parsed as UTC midnight, which local formatting can push a day early.
  const [year, month, day] = date.split('-').map(Number)
  return new Date(year!, month! - 1, day!).toLocaleDateString('de-DE', {weekday: 'short'})
}

function temp(value: number | null): string {
  return value === null || value === undefined ? '–' : `${Math.round(value)}°`
}

onMounted(async () => {
  visible.value = true

  await nextTick()
  if (forecastEl.value) {
    resizeObserver = new ResizeObserver(scheduleFit)
    resizeObserver.observe(forecastEl.value)
  }
  await document.fonts?.ready
  scheduleFit()
})

onBeforeUnmount(() => {
  cancelAnimationFrame(fitFrame)
  resizeObserver?.disconnect()
})
</script>

<template>
  <div v-show="visible && weatherData" ref="forecastEl" class="weather-forecast">
    <div v-if="weatherData?.hourly.length" class="weather-section">
      <div class="weather-section-title">Heute</div>
      <div class="weather-hourly">
        <div v-for="reading in weatherData.hourly" :key="reading.timestamp" class="weather-hour">
          <span class="weather-hour-label">{{ hourLabel(reading.timestamp) }}</span>
          <span class="weather-icon">{{ iconFor(reading.icon) }}</span>
          <span class="weather-hour-temp">{{ temp(reading.temperature) }}</span>
        </div>
      </div>
    </div>

    <div v-if="weatherData?.daily.length" class="weather-section">
      <div class="weather-section-title">Nächste 3 Tage</div>
      <div class="weather-daily">
        <div v-for="day in weatherData.daily" :key="day.date" class="weather-day">
          <span class="weather-day-label">{{ dayLabel(day.date) }}</span>
          <span class="weather-icon">{{ iconFor(day.icon) }}</span>
          <span class="weather-day-temps">
            <span class="weather-day-max">{{ temp(day.temp_max) }}</span>
            <span class="weather-day-min">{{ temp(day.temp_min) }}</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

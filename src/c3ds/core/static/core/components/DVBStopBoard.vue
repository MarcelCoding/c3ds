<script setup lang="ts">
import tramIcon from "../images/dvb/transport-tram-small.svg";
import busIcon from "../images/dvb/transport-bus-small.svg";
import plusbusIcon from "../images/dvb/transport-plusbus-small.svg";
import metropolitanIcon from "../images/dvb/transport-metropolitan-small.svg";
import ferryIcon from "../images/dvb/transport-ferry-small.svg";
import trainIcon from "../images/dvb/transport-train-small.svg";

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

const props = defineProps<{
  stop: StopDepartures
  now: number
}>()

// Best-effort mapping from the API's `Mot` field to DVB's own icon set. Values seen here
// haven't all been confirmed against a live response - anything unmapped falls back to `busIcon`.
const ICONS: Record<string, string> = {
  'Tram': tramIcon,
  'CityBus': busIcon,
  'Bus': busIcon,
  'IntercityBus': busIcon,
  'Regionalbus': busIcon,
  'PlusBus': plusbusIcon,
  'Metropolitan': metropolitanIcon,
  'Ferry': ferryIcon,
  'Train': trainIcon,
  'SuburbanRailway': trainIcon,
  'Rapidtransit': trainIcon,
}

function iconFor(mode: string): string {
  return ICONS[mode] ?? busIcon
}

function departureTime(dep: Departure): number {
  return new Date(dep.real_time ?? dep.scheduled).getTime()
}

function minutesUntil(dep: Departure): string {
  const diffMins = Math.round((departureTime(dep) - props.now) / 60000)
  return diffMins <= 0 ? 'jetzt' : `${diffMins} min`
}

// A delay is shown from the gap between real-time and schedule rather than the `State` field -
// the exact strings that field can take weren't confirmed against a live response.
function delayMinutes(dep: Departure): number {
  if (!dep.real_time) return 0
  const diffMs = new Date(dep.real_time).getTime() - new Date(dep.scheduled).getTime()
  return Math.round(diffMs / 60000)
}
</script>

<template>
  <div class="dvb-stop">
    <div class="dvb-stop-name">{{ stop.stop_name }}</div>
    <div v-if="stop.error || !stop.departures.length" class="dvb-stop-empty">
      {{ stop.error ? 'Keine Daten verfügbar' : 'Keine Abfahrten' }}
    </div>
    <div v-else class="dvb-departures">
      <div v-for="(dep, index) in stop.departures" :key="index" class="dvb-departure-row">
        <img :src="iconFor(dep.mode)" :alt="dep.mode" class="dvb-mode-icon"/>
        <span class="dvb-line">{{ dep.line }}</span>
        <span class="dvb-direction">{{ dep.direction }}</span>
        <span class="dvb-time">
          {{ minutesUntil(dep) }}
          <span v-if="delayMinutes(dep) > 0" class="dvb-delay">(+{{ delayMinutes(dep) }})</span>
        </span>
      </div>
    </div>
  </div>
</template>

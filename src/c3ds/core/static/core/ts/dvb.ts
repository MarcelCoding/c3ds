import {createApp} from 'vue'
import DVBView from "../components/DVBView.vue";

const container: HTMLElement|null = document.querySelector('div.dvb-container')
if (container !== null) {
  let dvbData = null
  const scriptEl = document.getElementById('dvb-data')
  if (scriptEl) {
    try {
      dvbData = JSON.parse((scriptEl as HTMLScriptElement).textContent || '')
    } catch (e) {
      console.error('Failed to parse DVB data:', e)
    }
  }

  createApp(DVBView, {dvbData}).mount('div.dvb-container')

  // Departures are fetched live and go stale within a minute, so refreshing them means
  // reloading the page - same jittered cadence as the weather/fediverse slides, so displays
  // showing several of these don't all reload in lockstep.
  const refreshInterval = Number(container.dataset['refreshInterval'])
  if (Number.isFinite(refreshInterval) && refreshInterval > 0) {
    const delay = refreshInterval * 1000 * (0.9 + 0.2 * Math.random())
    window.setTimeout(() => window.location.reload(), delay)
  }
}

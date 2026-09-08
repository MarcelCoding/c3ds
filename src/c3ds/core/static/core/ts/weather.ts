import {createApp} from 'vue'
import WeatherView from "../components/WeatherView.vue";

const container: HTMLElement|null = document.querySelector('div.weather-container')
if (container !== null) {
  let weatherData = null
  const scriptEl = document.getElementById('weather-data')
  if (scriptEl) {
    try {
      weatherData = JSON.parse((scriptEl as HTMLScriptElement).textContent || '')
    } catch (e) {
      console.error('Failed to parse weather data:', e)
    }
  }

  createApp(WeatherView, {
    weatherData
  }).mount('div.weather-container')

  // The hourly/daily picks are derived from the wall clock, so nothing pushes a reload as
  // they age - the display has to ask for a fresh page itself, on the same jittered cadence
  // as the fediverse slide: together they would otherwise reload in lockstep forever.
  const refreshInterval = Number(container.dataset['refreshInterval'])
  if (Number.isFinite(refreshInterval) && refreshInterval > 0) {
    const delay = refreshInterval * 1000 * (0.9 + 0.2 * Math.random())
    window.setTimeout(() => window.location.reload(), delay)
  }
}

import { format, parseISO, differenceInDays, startOfDay } from 'date-fns'
import { getCurrentTime, NTPClient } from "./ntp.ts";

declare const window: Window & typeof globalThis & {
 ntp?: NTPClient
}

(() => {
  const container = document.getElementById('clock')
  if (container === null || container.dataset['dayZero'] === undefined) return
  const dayElement = container.querySelector('p span')
  const timeElement = container.querySelector('p:last-child')
  const offsetElement = document.getElementById('ntp-time-offset')
  const latencyElement = document.getElementById('ntp-latency')
  if (dayElement === null || timeElement === null) return;
  const dayZero = parseISO(container.dataset['dayZero'])

  const update_time = () => {
    const now = getCurrentTime()
    const dayDiff = differenceInDays(startOfDay(now), startOfDay(dayZero))
    dayElement.textContent = dayDiff.toString()
    timeElement.textContent = format(now, 'HH:mm')

    if (offsetElement !== null) offsetElement.textContent = `Zeitabweichung: ${window.ntp?.offset?.toFixed(3)}ms`
    if (latencyElement !== null) latencyElement.textContent = `Latenz: ${window.ntp?.latency?.toFixed(3)}ms`

    window.setTimeout(() => {
      update_time()
    }, 1000 - now.getMilliseconds())
  }
  update_time()
})();

(() => {
  const resolutionElement = document.getElementById('screen-resolution')
  if (resolutionElement === null) return

  const update_resolution = () => {
    resolutionElement.textContent = `Auflösung: ${window.innerWidth}x${window.innerHeight}`
  }
  update_resolution()
  window.addEventListener('resize', update_resolution)
})()

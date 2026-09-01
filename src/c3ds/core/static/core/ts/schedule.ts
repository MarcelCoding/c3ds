import {ComponentPublicInstance, createApp} from 'vue'
import ScheduleView from "../components/ScheduleView.vue";
import axios from 'axios'
import {ScheduleJson, Schedule} from "../../../../static/ts/c3voc.ts";

declare const window: Window & typeof globalThis & {
 scheduleView?: ComponentPublicInstance<typeof ScheduleView>
}

const scheduleContainer: HTMLElement|null = document.querySelector('div.schedule-layout')
if (scheduleContainer !== null) {
  let room_filter: string[] = (scheduleContainer.dataset['roomFilter'] || '')
    .split(';')
    .filter((value) => {return value !== ''})
  let guid_filter: string[] = (scheduleContainer.dataset['guidFilter'] || '')
    .split(';')
    .filter((value) => {return value !== ''})
  let duration_limit: number | undefined = scheduleContainer.dataset['durationLimit'] ? Number(scheduleContainer.dataset['durationLimit']) : undefined
  let schedule_url: string = (scheduleContainer.dataset['scheduleUrl'] || '')
  let current_schedule: Schedule|null = null
  const scheduleView: ComponentPublicInstance<typeof ScheduleView> = createApp(ScheduleView, {
    // initialSchedule: schedule.schedule
    room_filter,
    guid_filter,
    duration_limit,
  }).mount('div.schedule-layout')
  window.scheduleView = scheduleView

  const legendContainer = document.querySelector('div.legend-container')
  
  const render_legend = () => {
    if (legendContainer) {
      const tracks = scheduleView.tracks as any
      if (tracks && Object.keys(tracks).length > 0) {
        let html = '<div class="legend flex flex-wrap flex-shrink-0">'
        for (let [, track] of Object.entries(tracks)) {
          html += `<div class="track text-3xl" style="border-color: ${(track as any).color || ''}">${(track as any).name}</div>`
        }
        html += '</div>'
        legendContainer.innerHTML = html
      }
    }
  }

  const load_data = () => {
    console.log('fetching schedule')
    axios.get(schedule_url)
    .then((resp) => {
      const schedule: ScheduleJson = resp.data
      if (current_schedule === null || current_schedule.version !== schedule.schedule.version) {
        console.log("schedule version %s loaded", schedule.schedule.version)
        current_schedule = schedule.schedule
        scheduleView.schedule = current_schedule
        setTimeout(render_legend, 100)
      } else {
        console.log('schedule unchanged')
      }
    })
  }
  load_data()
  window.setInterval(load_data, 5*60*1000)
}

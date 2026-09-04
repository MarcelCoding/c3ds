<script setup lang="ts">
import {Room, Schedule} from "../../../../static/ts/c3voc.ts"
import {ProcessedEvent} from "../ts/schedule_types.ts";
import {computed, ComputedRef, onMounted, ref} from "vue"
  import { addMilliseconds, isBefore } from 'date-fns'
  import ScheduleRow from "./ScheduleRow.vue";
import {getCurrentTime} from "../ts/ntp.ts";

  interface Track {
    name?: string;
    color?: string;
    slug?: string;
  }

  const props = withDefaults(defineProps<{
    initialSchedule?: Schedule
    room_filter?: string[]
    guid_filter?: string[]
    duration_limit?: number
    max_talks?: number
  }>(), {
    room_filter: () => [],
    guid_filter: () => [],
    duration_limit: undefined,
    max_talks: 7
  })

  const schedule = ref(props.initialSchedule)
  const now = ref(getCurrentTime())

  const tracks: ComputedRef<{[k: string]: Track}> = computed(() => {
    const tracks: {[k: string]: Track} = {}
    for (let track of schedule.value?.conference.tracks || []) {
      if (track.name) tracks[track.name] = track as Track
    }
    return tracks
  })

  // const rooms: ComputedRef<{[k: string]: Room}> = computed(() => {
  //   const rooms: {[k: string]: Room} = {}
  //   for (let room of schedule.value?.conference.rooms || []) {
  //     rooms[room.name] = room
  //   }
  //   return rooms
  // })

  const guid_rooms: ComputedRef<{[k: string]: Room}> = computed(() => {
    const guid_rooms: {[k: string]: Room} = {}
    for (let room of schedule.value?.conference.rooms || []) {
      if (room.guid) guid_rooms[room.guid] = room
    }
    return guid_rooms
  })

  const room_filter_combined: ComputedRef<string[]> = computed(() => {
    let guid_room_names: string[] = []
    if (props.guid_filter.length > 0) {
      for (let room_guid of props.guid_filter) {
        guid_room_names.push(guid_rooms.value[room_guid].name)
      }
    }
    if (props.room_filter.length > 0) {
      return guid_room_names.concat(props.room_filter)
    }
    return guid_room_names
  })

  const next_talks: ComputedRef<ProcessedEvent[]> = computed(() => {
    let max_talks = props.max_talks
    if (schedule?.value === undefined) {
      console.log('schedule missing')
      return []
    }
    let _next_talks: ProcessedEvent[] = []
    outerLoop: for (let day of schedule.value.conference.days) {
      roomsLoop: for (let room in day.rooms) {
        for (let event of day.rooms[room]) {
          const talk = event as ProcessedEvent
          if (room_filter_combined.value.length > 0 && !room_filter_combined.value.includes(talk.room)) {
            continue
          }
          talk.date_start = new Date(event.date)
          const durationMinutes = Number(talk.duration)
          talk.date_end = addMilliseconds(talk.date_start, durationMinutes * 60 * 1000)
          talk.moment_duration = durationMinutes
          if (props.duration_limit && talk.moment_duration > props.duration_limit) continue
          if (isBefore(talk.date_end, now.value)) continue
          talk.color = talk.track ? tracks.value[talk.track]?.color || '' : ''
          talk.speakers = talk.persons.map((person) => {
            return person.name || ''
          })
          _next_talks.push(talk)
          if (_next_talks.length >= max_talks) break outerLoop
        }
      }
    }
    const priorityRooms = ['One', 'Ground', 'Zero', 'Fuse']
    _next_talks.sort((a, b) => {
      // sort by start time and date
      if (a.date_start < b.date_start) return -1
      if (a.date_start > b.date_start) return 1

      // if it is the same, sort by room name

      // first check special rooms
      const aInPriorityRooms = priorityRooms.includes(a.room)
      const bInPriorityRooms = priorityRooms.includes(b.room)
      if (aInPriorityRooms || bInPriorityRooms) {
        if (!aInPriorityRooms) return 1
        if (!bInPriorityRooms) return -1
        return (priorityRooms.indexOf(a.room) < priorityRooms.indexOf(b.room)) ? -1: 1
      }

      // then sort alphabetical
      if (a.room < b.room) return -1
      if (a.room > b.room) return 1
      return 0
    })
    return _next_talks
  })

  function minute_tick() {
    now.value = getCurrentTime()
    const msUntilNextMinute = (60 - now.value.getSeconds() - 1) * 1000 + 1000 - now.value.getMilliseconds()
    window.setTimeout(() => {
      minute_tick()
    }, msUntilNextMinute)
  }
  
  onMounted(() => {
    console.log(`the component is now mounted.`)
    minute_tick()
  })

  defineExpose({
    schedule,
    now,
    minute_tick,
    tracks
  })
</script>

<template>
  <TransitionGroup name="list" tag="div" class="schedule flex flex-col flex-wrap overflow-hidden flex-grow text-fg">
    <ScheduleRow v-for="talk in next_talks" :key="talk.guid" :talk="talk"></ScheduleRow>
  </TransitionGroup>
</template>



import {Event} from "../../../../static/ts/c3voc.ts";

export interface ProcessedEvent extends Event {
  date_start: Date
  date_end: Date
  moment_duration: number
  color: string
  speakers: string[]
}
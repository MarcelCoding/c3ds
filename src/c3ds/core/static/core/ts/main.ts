import {WebSocketClient} from "./websocket.ts";
import {NTPClient} from "./ntp.ts";

const body = document.querySelector('body')
const displaySlug = body?.dataset['displaySlug']
const contentVersion = body?.dataset['contentVersion'] ?? null

declare const window: Window & typeof globalThis & {
 ntp?: NTPClient
}


// websocket stuff
if (displaySlug !== undefined) {
  console.log('Initializing Websocket Client')
  const ws = new WebSocketClient(displaySlug, true, contentVersion)
  const ntp = new NTPClient(ws)
  window.ntp = ntp
  window.setTimeout(() =>{
    ntp.sendNTPRequest()
  }, 1000)

  console.log('Client Initialized', ws)
}

import {WebSocketClient} from "./websocket.ts";
import {NTPClient} from "./ntp.ts";

const displaySlug = document.querySelector('body')?.dataset['displaySlug']

declare const window: Window & typeof globalThis & {
 ntp?: NTPClient
}


// websocket stuff
if (displaySlug !== undefined) {
  console.log('Initializing Websocket Client')
  const ws = new WebSocketClient(displaySlug, true)
  const ntp = new NTPClient(ws)
  window.ntp = ntp
  window.setTimeout(() =>{
    ntp.sendNTPRequest()
  }, 1000)

  console.log('Client Initialized', ws)
}

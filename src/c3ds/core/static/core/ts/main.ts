import {WebSocketClient} from "./websocket.ts";
import {NTPClient} from "./ntp.ts";
import {slideVisible} from "./slide.ts";

const body = document.querySelector('body')
const displaySlug = body?.dataset['displaySlug']
const contentVersion = body?.dataset['contentVersion'] ?? null
const buildId = body?.dataset['buildId'] ?? null

// What the entrance animations wait for. Both halves are needed: a playlist entry is loaded a
// whole turn before it is shown, and the headline font is declared font-display: block, so it
// draws no glyphs at all until the file has arrived. A fade started at first paint is over
// before anyone could have seen it.
Promise.all([slideVisible(), document.fonts.ready])
  .then(() => document.body.classList.add('slide-visible'))

declare const window: Window & typeof globalThis & {
 ntp?: NTPClient
}


// websocket stuff
if (displaySlug !== undefined) {
  console.log('Initializing Websocket Client')
  const ws = new WebSocketClient(displaySlug, true, contentVersion, buildId)
  const ntp = new NTPClient(ws)
  window.ntp = ntp
  window.setTimeout(() =>{
    ntp.sendNTPRequest()
  }, 1000)

  console.log('Client Initialized', ws)
}

export interface WebSocketCommand {
  cmd: string;
}

export interface ReceivedWebSocketCommand extends WebSocketCommand {
  receiveTimestamp: number;
}

export interface ReloadWebSocketCommand extends ReceivedWebSocketCommand {
  delayed?: boolean
}

export interface websocketMessageCallback { (cmd: ReceivedWebSocketCommand): void }

/** Window a delayed reload is scattered over, so a fleet of displays does not arrive at once. */
const RELOAD_SPREAD_MS = 20 * 1000

export class WebSocketClient {
  displaySlug: string
  /** Revision this page was rendered from; echoed on every ping so the server can spot a miss. */
  contentVersion: string | null
  /** Frontend build this page was served by; echoed too, since a deploy changes no content. */
  buildId: string | null
  ws: WebSocket | null = null
  heartbeatInterval: number | null = null
  unansweredPings: number = 0
  reloadTimer: number | null = null
  reloadDelayed: boolean = false
  callbacks: {[key: string]: websocketMessageCallback} = Object()

  constructor(displaySlug: string, autoconnect: boolean, contentVersion: string | null = null,
              buildId: string | null = null) {
    if (displaySlug === undefined || displaySlug == null) {
      throw Error('display slug missing')
    }
    this.displaySlug = displaySlug
    this.contentVersion = contentVersion
    this.buildId = buildId
    if (autoconnect) this.connect()
  }

  /**
   * A single edit sends one command per affected row, so several arrive for one save.
   * Repeats are ignored rather than rescheduled: drawing a fresh delay for each one and
   * letting the earliest win would collapse the spread back to nothing. An immediate
   * command still overtakes a reload that is merely scheduled.
   */
  reload(delayed: boolean = false) {
    const scheduled = this.reloadTimer !== null
    if (scheduled && !(this.reloadDelayed && !delayed)) return
    if (scheduled) window.clearTimeout(this.reloadTimer!)
    const timeout = delayed ? RELOAD_SPREAD_MS * Math.random() : 0
    this.reloadDelayed = delayed
    console.log(`reloading in ${timeout / 1000} seconds`)
    this.reloadTimer = window.setTimeout(() => {
      window.location.reload()
    }, timeout)
  }

  connect() {
    this.ws = new WebSocket(
      (window.location.protocol === 'https:' ? 'wss://' : 'ws://')
      +`${window.location.host}/ws/display/${this.displaySlug}/`
    )
    this.ws.onopen = () => {
      console.log('opening websocket');
      this.unansweredPings = 0
      this.startTimers()
      // Straight away rather than at the first interval, and on a reconnect as much as on the
      // first connection: the reply says whether this page is behind - a reload command sent
      // while it was loading, or while the socket was down, reached nobody. Reloading here on
      // spec instead would send the display back to the server for every passing hiccup.
      this.sendPing()
    }
    this.ws.onmessage = (e) => {
      const timeReceived = performance.now()
      console.log("got data from websocket:", e.data)
      const data: ReceivedWebSocketCommand = JSON.parse(e.data);
      data.receiveTimestamp = timeReceived

      switch (data?.cmd) {
        case 'reload':
          this.reload((data as ReloadWebSocketCommand).delayed === true)
          break;

        case 'pong':
          this.onPingReply()
          break;

        default:
          if (this.callbacks[data.cmd] !== undefined) {
            this.callbacks[data.cmd](data)
          } else {
            console.error('received unknown websocket cmd', data)
          }
      }
    }
    this.ws.onclose = () => {
      // Nothing to ping over a socket that is gone, and a send on one throws; the next onopen
      // starts the heartbeat again.
      this.stopTimers()
      this.reconnect()
    }
  }

  /** Called from onclose only, so the old socket is already gone by the time we get here. */
  reconnect() {
    const timeout = 5000 + 2000 * Math.random()
    console.log('WS connection died, reconnecting in %d', timeout)
    window.setTimeout(() => {
      this.connect()
    }, timeout)
  }

  startTimers() {
    this.stopTimers()
    this.heartbeatInterval = window.setInterval(() => {
      this.sendPing()
    }, 5000)
  }

  stopTimers() {
    if (this.heartbeatInterval !== null) window.clearInterval(this.heartbeatInterval)
    this.heartbeatInterval = null
  }

  sendPing() {
    console.log('sending ping')
    this.unansweredPings += 1
    // No pong for 300 sec: the socket is still up but nothing is answering over it. Drop it and
    // let onclose start a fresh one - reloading instead would ask an unreachable server for a
    // page and leave the display parked on a browser error, with no script left to recover.
    // Whatever it missed comes back from the ping the new connection opens with.
    if (this.unansweredPings > 30) {
      console.log('no pong for 30 pings, dropping the connection')
      this.ws?.close()
      return
    }
    this.ws?.send(JSON.stringify({
      cmd: 'ping',
      version: this.contentVersion,
      build: this.buildId,
    }))
  }

  onPingReply() {
    this.unansweredPings = 0
  }

  send_raw(data: (string | ArrayBufferLike | Blob | ArrayBufferView)) {
    this.ws?.send(data)
  }

  send(data: WebSocketCommand) {
    this.ws?.send(JSON.stringify(data))
  }

  registerCommand(command: string, callback: websocketMessageCallback) {
    if (this.callbacks[command] !== undefined) {
      throw Error(`command "${command}" already registered`)
    } else {
      this.callbacks[command] = callback
    }
  }

  unregisterCommand(command: string) {
    delete this.callbacks[command]
  }

}
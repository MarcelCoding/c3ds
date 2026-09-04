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
  ws: WebSocket | null = null
  heartbeatInterval: number | null = null
  unansweredPings: number = 0
  connectedBefore: boolean = false
  reloadTimer: number | null = null
  reloadDelayed: boolean = false
  callbacks: {[key: string]: websocketMessageCallback} = Object()

  constructor(displaySlug: string, autoconnect: boolean, contentVersion: string | null = null) {
    if (displaySlug === undefined || displaySlug == null) {
      throw Error('display slug missing')
    }
    this.displaySlug = displaySlug
    this.contentVersion = contentVersion
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
      if (this.connectedBefore) {
        // Every display reconnects at once after a restart, so spread these out: a server that
        // has just come back up is the worst moment to send the whole fleet at it together.
        console.log('reconnected after server restart, reloading page')
        this.reload(true)
        return
      }
      this.connectedBefore = true
      // Straight away rather than at the first interval: the reply also says whether a reload
      // command went out while this page was loading, when no socket was there to receive it.
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
      this.reconnect()
    }
  }

  reconnect() {
    this.ws?.close()
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
  }

  sendPing() {
    console.log('sending ping')
    this.unansweredPings += 1
    // No pong for 300 sec. Every display loses the server at the same moment, so spread the
    // reloads rather than have the whole fleet hit it the instant it answers again.
    if (this.unansweredPings > 30) this.reload(true)
    this.ws?.send(JSON.stringify({
      cmd: 'ping',
      version: this.contentVersion,
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
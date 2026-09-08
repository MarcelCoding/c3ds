/**
 * Playlist entries are rendered in an iframe so every view keeps its own layout and scripts.
 * A view that finishes on its own (a video reaching its end) tells the playlist to move on.
 *
 * The playlist loads an entry before it shows it, so "loaded" and "on screen" are not the same
 * moment any more. Anything that should start when a viewer can actually see it - playback, an
 * entrance animation, a fetch whose result animates in - waits for SLIDE_VISIBLE.
 */
export const SLIDE_ENDED = 'c3ds:slide-ended'
/** Sent by the playlist to the entry it has just put on screen. */
export const SLIDE_VISIBLE = 'c3ds:slide-visible'
/** Sent by an entry that has just loaded, asking whether it is the one on screen. */
export const SLIDE_HELLO = 'c3ds:slide-hello'

/** False when the view was opened on its own rather than as a playlist entry. */
const inPlaylist = () => window.parent !== window

export const reportSlideEnded = () => {
  if (!inPlaylist()) return
  window.parent.postMessage({ type: SLIDE_ENDED }, window.location.origin)
}

/**
 * Runs `callback` once this entry is on screen, or straight away when the view was not opened
 * as a playlist entry at all - so a view previewed on its own behaves as it always did.
 */
export const onSlideVisible = (callback: () => void) => {
  if (!inPlaylist()) {
    callback()
    return
  }

  const onMessage = (event: MessageEvent) => {
    if (event.origin !== window.location.origin) return
    if (event.source !== window.parent) return
    if (event.data?.type !== SLIDE_VISIBLE) return
    window.removeEventListener('message', onMessage)
    callback()
  }
  window.addEventListener('message', onMessage)

  // An entry that reloads itself in place - the fedi view rotates that way - comes back up while
  // it is already the one on screen, and will never be revealed again. Ask instead of waiting.
  window.parent.postMessage({ type: SLIDE_HELLO }, window.location.origin)
}

export const slideVisible = () => new Promise<void>((resolve) => onSlideVisible(() => resolve()))

/**
 * Playlist entries are rendered in an iframe so every view keeps its own layout and scripts.
 * A view that finishes on its own (a video reaching its end) tells the playlist to move on.
 */
export const SLIDE_ENDED = 'c3ds:slide-ended'

export const reportSlideEnded = () => {
  if (window.parent === window) return
  window.parent.postMessage({ type: SLIDE_ENDED }, window.location.origin)
}

import videojs from 'video.js'
import 'video.js/dist/video-js.css'
import { onSlideVisible, reportSlideEnded } from './slide.ts'

(() => {
  const container = document.getElementById('video')
  if (container === null) return
  const src = container.dataset['src']
  const type = container.dataset['type']
  if (src === undefined || type === undefined) return

  const player = videojs(container, {
    controls: false,
    fill: true,
    loop: container.dataset['loop'] === '1',
  })
  // Sourced now so it buffers while the entry is still hidden, played only once it is up: an
  // entry is loaded a turn ahead, and a video that ran out behind the scenes would sit there
  // already ended, its report of that ignored, stranding the playlist on it.
  player.src({ src, type })
  onSlideVisible(() => {
    player.play()?.catch(() => {
      // Autoplay with sound is blocked until the user interacts with the page — a display never does.
      player.muted(true)
      player.play()
    })
  })

  // A looping video never ends; the playlist advances those on a timer instead.
  player.on('ended', reportSlideEnded)
  player.on('error', () => {
    console.error('video playback failed:', player.error())
    reportSlideEnded()
  })
})()

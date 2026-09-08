import { SLIDE_ENDED, SLIDE_HELLO, SLIDE_VISIBLE } from './slide.ts'

type PlaylistItem = {
  url: string
  /** Seconds to show the entry, or null to wait for it to report that it finished. */
  duration: number | null
}

/** An entry is loaded well before it is shown, so the two states are tracked separately. */
type SlideState = 'empty' | 'loading' | 'ready'

const parseItems = (data: string): PlaylistItem[] => {
  try {
    const parsed = JSON.parse(data)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item) => typeof item?.url === 'string' && item.url !== '')
  } catch (e) {
    console.error('failed to parse playlist:', e)
    return []
  }
};

(() => {
  const container = document.getElementById('playlist')
  if (container === null) return

  const items = parseItems(container.dataset['items'] || '[]')
  if (items.length === 0) {
    console.warn('playlist is empty')
    return
  }

  const state: SlideState[] = items.map(() => 'empty')
  let current = 0
  let timer: number | undefined
  /** Set while an entry that should be on screen is still loading, so its load reveals it. */
  let pending: number | null = null

  const slides = items.map((_item, index) => {
    const slide = document.createElement('iframe')
    slide.className = 'playlist-slide'
    slide.setAttribute('referrerpolicy', 'no-referrer')
    slide.addEventListener('load', () => {
      // Unloading an entry (src set to about:blank) fires this too.
      if (state[index] !== 'loading') return
      state[index] = 'ready'
      if (pending === index) reveal(index)
    })
    container.append(slide)
    return slide
  })

  const advance = () => show((current + 1) % items.length)

  const load = (index: number) => {
    if (state[index] !== 'empty') return
    state[index] = 'loading'
    slides[index]!.src = items[index]!.url
  }

  const unload = (index: number) => {
    if (state[index] === 'empty') return
    state[index] = 'empty'
    // Otherwise it keeps playing behind the entry that is on screen.
    slides[index]!.src = 'about:blank'
  }

  const reveal = (index: number) => {
    pending = null
    const previous = current
    current = index
    slides[index]!.classList.add('is-active')
    // Only now: an entry loaded a whole turn ago must not start playing, or animating, until a
    // viewer can see it.
    slides[index]!.contentWindow?.postMessage({ type: SLIDE_VISIBLE }, window.location.origin)

    if (previous !== index) {
      slides[previous]!.classList.remove('is-active')
      unload(previous)
    }
    // Timed from the reveal, not from the load, so loading ahead cannot shorten a turn.
    const duration = items[index]!.duration
    if (duration !== null) timer = window.setTimeout(advance, duration * 1000)

    // The next entry gets this entry's whole turn to load and paint, so the switch to it is a
    // plain visibility flip rather than a wait on the network.
    load((index + 1) % items.length)
  }

  const show = (index: number) => {
    window.clearTimeout(timer)

    // Re-showing the entry that is already up has to fetch it again - assigning the same src
    // would not - and reloading in place keeps the old render on screen while it does.
    if (index === current && state[index] !== 'empty') {
      pending = index
      state[index] = 'loading'
      slides[index]!.contentWindow?.location.reload()
      return
    }

    if (state[index] === 'ready') {
      reveal(index)
      return
    }
    // Still loading, or never started: it stays hidden behind the entry on screen until it is
    // rendered, so nothing ever shows an unpainted frame.
    pending = index
    load(index)
  }

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return

    if (event.data?.type === SLIDE_HELLO) {
      // An entry asking whether it is the one on screen, because it may have missed the reveal.
      const index = slides.findIndex((slide) => slide.contentWindow === event.source)
      if (index === current && state[index] === 'ready') {
        slides[index]!.contentWindow?.postMessage({ type: SLIDE_VISIBLE }, window.location.origin)
      }
      return
    }

    if (event.data?.type !== SLIDE_ENDED) return
    if (event.source !== slides[current]!.contentWindow) return
    advance()
  })

  show(0)
})()

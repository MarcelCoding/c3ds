import { SLIDE_ENDED } from './slide.ts'

type PlaylistItem = {
  url: string
  /** Seconds to show the entry, or null to wait for it to report that it finished. */
  duration: number | null
}

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

  const slides = items.map(() => {
    const slide = document.createElement('iframe')
    slide.className = 'playlist-slide'
    slide.setAttribute('referrerpolicy', 'no-referrer')
    container.append(slide)
    return slide
  })

  let current = 0
  let timer: number | undefined

  const advance = () => show((current + 1) % items.length)

  const show = (next: number) => {
    const item = items[next]!
    const slide = slides[next]!
    const previous = current
    current = next
    window.clearTimeout(timer)

    slide.addEventListener('load', () => {
      // Only reveal the next entry once it is rendered, so the previous one covers the load.
      slide.classList.add('is-active')
      if (previous !== next) {
        slides[previous]!.classList.remove('is-active')
        // Unload it, otherwise it keeps playing behind the current entry.
        slides[previous]!.src = 'about:blank'
      }
      if (item.duration !== null) timer = window.setTimeout(advance, item.duration * 1000)
    }, { once: true })

    // Re-showing the only entry in a playlist has to reload it, assigning the same src would not.
    if (previous === next && slide.src !== '') slide.contentWindow?.location.reload()
    else slide.src = item.url
  }

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return
    if (event.data?.type !== SLIDE_ENDED) return
    if (event.source !== slides[current]!.contentWindow) return
    advance()
  })

  show(0)
})()

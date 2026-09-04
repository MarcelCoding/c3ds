import {createApp} from 'vue'
import MastodonPostView from "../components/MastodonPostView.vue";

const container: HTMLElement|null = document.querySelector('div.mastodon-post-container')
if (container !== null) {
  let postData = null
  const scriptEl = document.getElementById('mastodon-post-data')
  if (scriptEl) {
    try {
      postData = JSON.parse((scriptEl as HTMLScriptElement).textContent || '')
    } catch (e) {
      console.error('Failed to parse post data:', e)
    }
  }
  
  createApp(MastodonPostView, {
    postData
  }).mount('div.mastodon-post-container')

  // The server picks a post per request, so re-requesting the view is what rotates it.
  // Jittered by a tenth: displays that reloaded together would otherwise come back in
  // lockstep, every interval, for as long as they run.
  const refreshInterval = Number(container.dataset['refreshInterval'])
  if (Number.isFinite(refreshInterval) && refreshInterval > 0) {
    const delay = refreshInterval * 1000 * (0.9 + 0.2 * Math.random())
    window.setTimeout(() => window.location.reload(), delay)
  }
}

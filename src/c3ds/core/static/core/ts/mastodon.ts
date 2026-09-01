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
}

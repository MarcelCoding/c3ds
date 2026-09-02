<script setup lang="ts">
import {onMounted, onBeforeUnmount, nextTick, ref, computed} from "vue";
import DOMPurify from 'dompurify';

interface Account {
  display_name: string
  username: string
  url: string
  avatar: string
}

interface MediaAttachment {
  id: string
  type: string
  url: string
  preview_url?: string
  description?: string
  meta?: {
    original?: { width?: number, height?: number }
  }
}

interface PostData {
  id: string
  content: string
  created_at: string
  account: Account
  url: string
  reblogs_count: number
  replies_count: number
  favourites_count: number
  hashtag: string
  media_attachments?: MediaAttachment[]
}

const props = defineProps<{
  postData: PostData | null
}>()

const formattedDate = ref('')
const relativeTime = ref('')
const visible = ref(false)
const postEl = ref<HTMLElement | null>(null)

const MIN_FONT_SIZE = 6
const MAX_FONT_SIZE = 20

let fitFrame = 0
let resizeObserver: ResizeObserver | null = null
let timeInterval = 0

function fits(el: HTMLElement) {
  return el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1
}

function fitToContainer() {
  const el = postEl.value
  if (!el || !el.clientHeight) return

  let low = MIN_FONT_SIZE
  let high = MAX_FONT_SIZE
  let best = MIN_FONT_SIZE
  for (let i = 0; i < 14; i++) {
    const mid = (low + high) / 2
    el.style.fontSize = `${mid}px`
    if (fits(el)) {
      best = mid
      low = mid
    } else {
      high = mid
    }
  }
  el.style.fontSize = `${best}px`
}

function scheduleFit() {
  cancelAnimationFrame(fitFrame)
  fitFrame = requestAnimationFrame(fitToContainer)
}

const sanitizedContent = computed(() => {
  if (!props.postData?.content) return ''
  return DOMPurify.sanitize(props.postData.content, {
    ALLOWED_TAGS: ['a', 'em', 'strong', 'br', 'p', 'span', 'code', 'pre'],
    ALLOWED_ATTR: ['href', 'rel', 'target', 'class', 'style'],
  })
})

const images = computed(() =>
  (props.postData?.media_attachments ?? []).filter(m => m.type === 'image')
)

const handle = computed(() => {
  const account = props.postData?.account
  if (!account) return ''
  try {
    return `@${account.username}@${new URL(account.url).host}`
  } catch {
    return `@${account.username}`
  }
})

function formatTime() {
  if (!props.postData) return
  const created = new Date(props.postData.created_at)
  formattedDate.value = created.toLocaleDateString('de-DE', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
  
  const now = new Date()
  const diffMs = now.getTime() - created.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  
  if (diffMins < 1) relativeTime.value = 'gerade eben'
  else if (diffMins < 60) relativeTime.value = `vor ${diffMins} Minuten`
  else if (diffHours < 24) relativeTime.value = `vor ${diffHours} Stunden`
  else relativeTime.value = `vor ${diffDays} Tagen`
}

onMounted(async () => {
  formatTime()
  timeInterval = window.setInterval(() => {
    formatTime()
    scheduleFit()
  }, 60000)
  visible.value = true

  await nextTick()
  if (postEl.value) {
    resizeObserver = new ResizeObserver(scheduleFit)
    resizeObserver.observe(postEl.value)
  }
  await document.fonts?.ready
  scheduleFit()
})

onBeforeUnmount(() => {
  cancelAnimationFrame(fitFrame)
  clearInterval(timeInterval)
  resizeObserver?.disconnect()
})
</script>

<template>
  <div
    v-show="visible && postData"
    ref="postEl"
    class="mastodon-post"
    :class="{ image: images.length }"
  >
    <div class="mastodon-content-area">
      <div class="mastodon-post-header">
        <img
          :src="postData!.account.avatar"
          :alt="postData!.account.display_name"
          class="mastodon-avatar"
          @load="scheduleFit"
        />
        <div class="mastodon-account">
          <span class="mastodon-display-name">{{ postData!.account.display_name }}</span>
          <span class="mastodon-username">{{ handle }}</span>
          <span class="mastodon-time">{{ relativeTime }}</span>
        </div>
      </div>
      <div class="mastodon-content" v-html="sanitizedContent"></div>
    </div>
    <div v-if="images.length" class="mastodon-media" :data-count="Math.min(images.length, 4)">
      <img
        v-for="media in images"
        :key="media.id"
        :src="media.url"
        :alt="media.description || 'Image'"
        :width="media.meta?.original?.width"
        :height="media.meta?.original?.height"
        class="mastodon-image"
        @load="scheduleFit"
      />
    </div>
  </div>
</template>

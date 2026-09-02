<script setup lang="ts">
import {onMounted, ref, computed} from "vue";
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

const sanitizedContent = computed(() => {
  if (!props.postData?.content) return ''
  return DOMPurify.sanitize(props.postData.content, {
    ALLOWED_TAGS: ['a', 'em', 'strong', 'br', 'p', 'span', 'code', 'pre'],
    ALLOWED_ATTR: ['href', 'rel', 'target', 'class', 'style'],
  })
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

onMounted(() => {
  formatTime()
  setInterval(formatTime, 60000)
  visible.value = true
})
</script>

<template>
  <div v-show="visible && postData" class="mastodon-post">
    <div class="mastodon-post-header">
      <img 
        :src="postData!.account.avatar" 
        :alt="postData!.account.display_name"
        class="mastodon-avatar"
      />
      <div class="mastodon-account">
        <span class="mastodon-display-name">{{ postData!.account.display_name }}</span>
        <span class="mastodon-username">@{{ postData!.account.username }}</span>
        <span class="mastodon-time">{{ relativeTime }}</span>
      </div>
    </div>
    <div class="mastodon-content-area">
      <div class="mastodon-content" v-html="sanitizedContent"></div>
      <div v-if="postData!.media_attachments?.length" class="mastodon-media">
        <img 
          v-for="media in postData!.media_attachments.filter(m => m.type === 'image')" 
          :key="media.id"
          :src="media.url" 
          :alt="media.description || 'Image'"
          class="mastodon-image"
          loading="lazy"
        />
      </div>
    </div>
  </div>
</template>

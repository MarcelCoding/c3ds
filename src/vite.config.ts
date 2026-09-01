import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { djangoVitePlugin } from 'django-vite-plugin'


// https://vite.dev/config/
export default defineConfig({
  build: {
    sourcemap: true,
    target: [
      'es2020',
      'chrome70',
    ],
  },
  assetsInclude: ['**/*.woff', '**/*.woff2', '**/*.otf', '**/*.ttf'],
  plugins: [
    vue(),
    djangoVitePlugin({
      input: [
        'c3ds/static/css/base.scss',
        'c3ds/core/static/core/ts/main.ts',
        'c3ds/core/static/core/ts/clock.ts',
        'c3ds/core/static/core/ts/schedule.ts',
        'c3ds/core/static/core/ts/playlist.ts',
        'c3ds/core/static/core/ts/video.ts',
        'c3ds/core/static/core/ts/mastodon.ts',
      ],
    }),
    {
      name: 'fix-css-urls',
      transform(code) {
        return code.replace(
          /http:\/\/__django_vite_plugin_placeholder__\.protibimbok/g,
          'http://127.0.0.1:5173'
        );
      },
    },
  ],
  server: {
    host: '127.0.0.1',
    port: 5173,
    fs: {
      allow: [
        '/home/marcel/workspace/tmp/c3ds/src',
        '/home/marcel/workspace/tmp/c3ds/src/c3ds',
      ],
    },
  }
})

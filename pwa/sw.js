/* 医疗岗位雷达 - Service Worker（离线缓存） */
const CACHE_NAME = 'jobradar-v3';
const STATIC_ASSETS = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
];

// 网络优先的资源：数据文件 + 页面入口 + 前端代码（保证能拿到最新版）
const NETWORK_FIRST = [
  'jobs.json',
  'index.html',
  'app.js',
  'style.css',
];

// 安装：缓存静态资源
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// 激活：清理旧缓存
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// 拦截请求
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // 网络优先：拉最新，成功则更新缓存，失败（离线）回退缓存
  if (NETWORK_FIRST.some(name => url.pathname.endsWith(name))) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // 其他静态资源（图标、manifest 等）：缓存优先
  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        return response;
      });
    })
  );
});

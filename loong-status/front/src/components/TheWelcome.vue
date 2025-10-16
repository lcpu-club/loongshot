<template>
  <div class="container">
    <!-- Title -->
    <div class="upper-layer">
      <div class="header-content">
        <img src="/public/logo.png" class="logo" alt="LoongArch Logo">
        <h1>Arch Linux for Loong64</h1>
        <p class="subtitle">
          This is a port of 
          <a href="https://archlinux.org/">Arch Linux</a> 
          for <a href="https://www.loongson.cn/EN">Loong64</a> 
          architecture.
        </p>
      </div>
    </div>

    <div class="lower-layer">
      <!-- Router -->
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>

      <!-- Stats -->
      <div class="stats-container">
        <h2 class="stats-title">Package Statistics</h2>
        <Stat />
      </div>
    </div>

    <!-- Navigators -->
    <div class="nav-container">
      <div 
        v-for="(item, index) in navItems" 
        :key="index"
        class="nav-orb"
        @click="navigateTo(item.path)"
      >
        <component :is="item.icon" class="orb-icon" />
        <span class="orb-text">{{ item.text }}</span>
      </div>
    </div>

    <!-- Mirror -->
    <div class="repo-footer">
      Mirror: 
      <a href="https://mirrors.pku.edu.cn/loongarch-lcpu/archlinux/">
        https://mirrors.pku.edu.cn/loongarch-lcpu/archlinux/
      </a>
    </div>
  </div>
</template>

<script setup>
import { Document, Collection, Tools, Download } from '@element-plus/icons-vue'
import Stat from './Stat.vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const navItems = [
  { 
    text: 'Status',
    path: '/status',
    icon: Document,
  },
  { 
    text: 'Patches',
    path: 'https://github.com/lcpu-club/loongarch-packages',
    icon: Collection,
  },
  { 
    text: 'Infra',
    path: 'https://github.com/lcpu-club/loongshot',
    icon: Tools,
  },
  { 
    text: 'Download ISO',
    path: 'https://mirrors.wsyu.edu.cn/loongarch/archlinux/iso/latest/archlinux-loong64.iso',
    icon: Download,
  }
]

const navigateTo = (path) => {
  if (path.startsWith('http')) {
    window.open(path, '_blank')
  } else {
    router.push(path)
  }
}
</script>

<style scoped>
.container {
min-height: 100vh;
display: flex;
flex-direction: column;
border-radius: 5px; 
overflow: hidden; 
}

.upper-layer {
  background: #9b2d35;
  padding: 2rem 1rem;
  text-align: center;
}

.header-content {
  max-width: 800px;
  margin: 0 auto;
}

.logo {
  height: 80px;
  width: 80px;
  margin-bottom: 1rem;
}

h1 {
  color: white;
  font-size: 2.5rem;
  margin-bottom: 1rem;
}

.subtitle {
  color: rgba(255,255,255,0.9);
  font-size: 1.1rem;
}

.subtitle a {
  color: #ffd04b;
  text-decoration: none;
  border-bottom: 1px dashed;
}

.lower-layer {
  flex: 1;
  padding: 2rem 1rem;
  background: #f8f9fa;
}

.stats-container {
  max-width: 1000px;
  margin: 2rem auto;
  padding: 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.1);
}

.stats-title {
  text-align: center;
  color: #9b2d35;
  margin-bottom: 1.5rem;
}

.nav-container {
  display: flex;
  justify-content: center;
  gap: 2rem;
  padding: 2rem;
  background: white;
  border-top: 1px solid #eee;
}

.nav-orb {
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  border-radius: 50px;
  transition: all 0.3s;
  width: 100px;
}

.nav-orb:hover {
  background: #9b2d3510;
  transform: translateY(-3px);
}

.orb-icon {
  font-size: 2rem;
  color: #9b2d35;
}

.orb-text {
  font-size: 0.9rem;
  color: #444;
  text-align: center;
  white-space: nowrap;
}

.repo-footer {
  text-align: center;
  padding: 1rem;
  background: #f8f9fa;
  border-top: 1px solid #eee;
}

.repo-footer a {
  color: #9b2d35;
  text-decoration: none;
}

/* Animations */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 768px) {
  h1 {
    font-size: 2rem;
  }

  .nav-container {
    flex-wrap: wrap;
    gap: 1rem;
  }

  .nav-orb {
    width: 80px;
    padding: 0.8rem;
  }

  .orb-icon {
    font-size: 1.5rem;
  }

  .orb-text {
    font-size: 0.8rem;
  }
}
</style>
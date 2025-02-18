import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/status',
      name: 'status',
      component: () => import('../views/Status.vue'),
    },
    {
      path: '/stat',
      name: 'stat',
      component: () => import('../views/Stat.vue'),
    },
  ],
})

export default router

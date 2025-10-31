import { createRouter, createWebHistory } from "vue-router";
import HomeView from "../views/HomeView.vue";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
    },
    {
      path: "/status",
      name: "status",
      component: () => import("../views/Status.vue"),
    },
    {
      path: "/stat",
      name: "stat",
      component: () => import("../views/Stat.vue"),
    },
    {
      path: "/task",
      name: "task",
      component: () => import("../views/TaskView.vue"),
    },
    {
      path: "/log",
      name: "log",
      component: () => import("../views/LogView.vue"),
    },
    {
      path: "/:pathMatch(.*)*",
      name: "NotFound",
      component: () => import("../views/NotFound.vue"),
    },
  ],
});

export default router;

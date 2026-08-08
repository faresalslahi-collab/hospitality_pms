import { createRouter, createWebHistory } from 'vue-router'

import { session } from '@/stores/session'

/**
 * Routes are grouped exactly as the approved route map in Frontend Standards
 * section 4. Each build registers its own routes here.
 *
 * `meta.roles` hides a route from users who cannot use it. It is navigation
 * comfort, never a security boundary.
 */
const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
  },
  {
    path: '/rooms',
    name: 'RoomRack',
    component: () => import('@/pages/RoomRack.vue'),
  },
  {
    path: '/availability',
    name: 'Availability',
    component: () => import('@/pages/Availability.vue'),
  },
  {
    path: '/reservations',
    name: 'Reservations',
    component: () => import('@/pages/Reservations.vue'),
  },
  {
    path: '/reservations/:id',
    name: 'Reservation',
    component: () => import('@/pages/Reservation.vue'),
  },
  {
    path: '/in-house',
    name: 'InHouse',
    component: () => import('@/pages/InHouse.vue'),
  },
  {
    path: '/forbidden',
    name: 'Forbidden',
    component: () => import('@/pages/Forbidden.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/pages/NotFound.vue'),
  },
]

const router = createRouter({
  history: createWebHistory('/pms'),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  if (!session.isLoaded.value) {
    try {
      await session.load()
    } catch {
      // The session endpoint refuses Guest, so an unauthenticated deep link
      // returns to login and comes back to where the user was heading.
      window.location.href = `/login?redirect-to=${encodeURIComponent('/pms' + to.fullPath)}`
      return false
    }
  }

  if (to.meta.roles?.length && !session.hasRole(to.meta.roles)) {
    return { name: 'Forbidden' }
  }

  return true
})

export default router

<!--
  Contextual operational detail with its related quick actions, opened beside the
  board the user is working (16.7.0 UI kit).

  It exists because the arrivals, departures and in-house boards ask a question a
  modal answers badly: "what is going on with this one, and what can I do about
  it, without losing my place in the list". A modal takes the board away; this
  panel sits alongside it.

  It complements the existing dialogs, it does not replace them. A short isolated
  action — assign a room, take a payment, extend or shorten a stay — is still a
  dialog, launched from inside this panel if that is where the user is.

  It is presentation only: no resource, no request, no permission decision and no
  clock. The caller supplies an already-translated title, the content, and the
  actions; the panel supplies the shell, the focus contract and the states.

  One component serves both directions. The panel is pinned to the *logical* end
  with `inset-y-0 end-0`, so the browser puts it at the end of the reading
  direction — the trailing side in English, the leading one in Arabic — with no
  script, no mirrored copy and nothing for a future screen to get wrong.
-->
<template>
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 z-40">
      <div
        class="absolute inset-0 bg-black/30"
        aria-hidden="true"
        data-drawer-overlay
        @click="onOverlayClick"
      />

      <aside
        ref="panel"
        class="absolute inset-y-0 end-0 flex w-full flex-col border-s border-outline-gray-1 bg-surface-white shadow-xl outline-none"
        :class="widthClass"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        data-drawer-panel
      >
        <!-- Header, content and footer are separate flex children so that only
             the middle one scrolls: the title the panel is labelled by, and the
             actions the user is reaching for, must not scroll out of reach. -->
        <header class="flex items-start gap-2 border-b border-outline-gray-1 px-4 py-3">
          <div class="min-w-0 flex-1 text-start">
            <h2 :id="titleId" class="truncate text-base font-semibold text-ink-gray-9">
              {{ title }}
            </h2>
            <p v-if="subtitle" class="truncate text-p-sm text-ink-gray-6">{{ subtitle }}</p>
            <slot name="header" />
          </div>

          <!-- Stays enabled while loading and while showing an error: a panel the
               user cannot leave is worse than the failure it is reporting. -->
          <Button
            variant="ghost"
            :aria-label="t('ui.drawer.close_label')"
            :title="t('common.close')"
            data-drawer-close
            @click="requestClose"
          >
            <template #icon><FeatherIcon name="x" class="size-4" /></template>
          </Button>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4" data-drawer-content>
          <LoadingState v-if="loading" />
          <ErrorState v-else-if="error" :error="error" />
          <slot v-else />
        </div>

        <footer
          v-if="$slots.footer"
          class="flex flex-wrap items-center justify-end gap-2 border-t border-outline-gray-1 px-4 py-3"
        >
          <slot name="footer" />
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<!--
  Module scope, not component scope: the page scroll is one shared thing, so the
  lock below is counted across every open panel.
-->
<script>
/**
 * Page scroll lock, shared by every instance.
 *
 * Two panels open at once is not a layout we build, but the second one closing
 * must not hand the page back while the first is still covering it — hence a
 * count, and the previous inline value rather than an assumed default.
 */
let locks = 0
let previousOverflow = ''

function lockBodyScroll() {
  if (locks === 0) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }

  locks += 1
}

function releaseBodyScroll() {
  locks = Math.max(0, locks - 1)

  if (locks === 0) document.body.style.overflow = previousOverflow
}
</script>

<script setup>
import { Button, FeatherIcon } from 'frappe-ui'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'

import ErrorState from '@/components/states/ErrorState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { t } from '@/utils/i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** Already translated by the caller: it is usually a guest or room name. */
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  /** Anything `normaliseError` understands; ErrorState does the normalising. */
  error: { type: [Object, String], default: null },
  width: { type: String, default: 'md' },
  closeOnEscape: { type: Boolean, default: true },
  closeOnOverlay: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'close'])

const titleId = useId()

const panel = ref(null)

/**
 * The element that had focus when the panel opened.
 *
 * Returning focus to it on close is the part of a drawer that is invisible when
 * it works: a keyboard user who opened the panel from a row action lands back on
 * that row action, not at the top of the document.
 */
let returnFocusTo = null
let active = false

/** Full width on a phone, a readable column from `sm` up. */
const WIDTHS = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-md',
  lg: 'sm:max-w-lg',
  xl: 'sm:max-w-xl',
}

const widthClass = computed(() => WIDTHS[props.width] || WIDTHS.md)

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusables() {
  if (!panel.value) return []

  return Array.from(panel.value.querySelectorAll(FOCUSABLE)).filter(
    (element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true',
  )
}

function requestClose() {
  emit('update:modelValue', false)
  emit('close')
}

function onOverlayClick() {
  if (props.closeOnOverlay) requestClose()
}

function focusInitial() {
  const items = focusables()
  const target = items[0] || panel.value?.querySelector('[data-drawer-close]') || panel.value

  target?.focus()
}

function restoreFocus() {
  // A trigger that has since been unmounted — a row action on a board that
  // refreshed while the panel was open — is not focusable any more, and forcing
  // focus onto a detached node would silently move it to the document body.
  if (returnFocusTo?.isConnected && typeof returnFocusTo.focus === 'function') {
    returnFocusTo.focus()
  }

  returnFocusTo = null
}

/**
 * Keep Tab inside the panel.
 *
 * Handled on the document rather than the panel so that focus which has already
 * escaped — the browser toolbar, or a click on the page behind — is pulled back
 * on the next Tab instead of walking the page underneath the overlay.
 */
function onKeydown(event) {
  if (!active) return

  if (event.key === 'Escape') {
    if (props.closeOnEscape) {
      event.preventDefault()
      requestClose()
    }

    return
  }

  if (event.key !== 'Tab' || !panel.value) return

  const items = focusables()

  if (!items.length) {
    event.preventDefault()
    panel.value.focus()

    return
  }

  const first = items[0]
  const last = items[items.length - 1]
  const focused = document.activeElement
  const escaped = !panel.value.contains(focused)
  const edge = event.shiftKey ? first : last

  if (escaped || focused === edge) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  }
}

function activate() {
  if (active) return

  active = true
  returnFocusTo = document.activeElement
  lockBodyScroll()
  document.addEventListener('keydown', onKeydown)
  nextTick(focusInitial)
}

function deactivate() {
  if (!active) return

  active = false
  document.removeEventListener('keydown', onKeydown)
  releaseBodyScroll()
  restoreFocus()
}

onMounted(() => {
  if (props.modelValue) activate()
})

watch(
  () => props.modelValue,
  (open) => (open ? activate() : deactivate()),
)

// A board that navigates away while the panel is open unmounts it without ever
// setting `modelValue` to false; without this the page stays unscrollable.
onBeforeUnmount(deactivate)
</script>

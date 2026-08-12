<!--
  Rooms & rates: one card per room line, and every verb that acts on one of them.

  This is the tab a multi-room booking is actually run from, so the whole of it is
  built around one rule: **a room line is an operational room, and the lines are
  independent.** After confirmation `normalise_room_lines` guarantees one physical
  room per row — a row is what holds an assignment, becomes a Stay, opens a folio
  and takes a share of the deposit — so each card carries its own interval, its own
  occupancy, its own plan, its own money and its own controls, and every control
  sends the name of the line it sits on. There is no bulk verb here: no "assign all",
  no per-line cancel (cancellation is a whole-booking transition and lives in the
  header), and no place where one line's dates, rate or status stand in for the
  booking's.

  Six things this tab deliberately does, each because the alternative would put a
  false statement on screen:

  1. **`room_rate` is labelled as an average, never as "the rate".** It is
     `total_amount / nights` *including* extra-adult, extra-child and extra-bed
     supplements, so on any stay with a weekend uplift or a package free night it
     equals no actual night of the stay. The real per-night figures are in
     `rate_lines` and open in a breakdown beside it.

  2. **The door number is preferred over the docname.** `assigned_room` is a Hotel
     Room name, which is the room *code* (`DOHA01-405`); `room_number` is what an
     agent says out loud (`405`). Where the caller may not read Hotel Room the
     enrichment keys are absent altogether, and the code is then shown plainly with
     no readiness claim attached — not a "ready" or "not ready" word this screen
     never received. The same rule holds for the two other docnames on a line:
     `room_type_name` and `rate_plan_name` are gated on **Room Type** and **Rate
     Plan** respectively — three separate clearances, not one — and where a name is
     absent the line's own column is shown as the code it is.

  3. **Per-line status comes from the line's Stay, or is not shown at all.**
     `Reservation Room.reservation_status` is a copy of the header status, stamped
     identically onto all three lines of a three-room booking by `_propagate_status`,
     so it cannot answer the one per-line question an agent has — which room is in
     house. It is never rendered. `stay_status` is, when a `stay` is present, and
     when there is none there is no badge.

  4. **Once a line has a Stay, the room the guest is in is `stay_room`.**
     `stays.change_room` moves the Stay and the folio and never writes back to
     `assigned_room`, so after a room move the reservation line still names the room
     the guest left. The door number the workspace enriches is looked up from
     `assigned_room`, so it is only used when the two agree.

  5. **Assign Room is never offered on a line that has a Stay.** The guest is in a
     room; the verb for that is Change Room, it belongs to the Stay (it moves the
     folio too), and this tab links there rather than reimplementing it.

  6. **There is no rate comparison anywhere on this tab.** "Booked rate versus
     today's rate" was considered and dropped: `get_rate_breakdown` never consults a
     negotiated corporate rate, so for a corporate booking the difference displayed
     would be the contract discount and the panel would tell an agent the hotel is
     out of pocket by an amount it agreed to.

  7. **A rate plan is chosen; a rate never is.** `set_line_rate_plan` takes no rate
     parameter and neither does the service beneath it — `price_reservation` asks
     `get_rate_breakdown` what the chosen plan costs for these nights and this
     occupancy, and overwrites whatever anyone believed the figure to be. The picker
     therefore offers plans and shows no money at all, and it offers only the plans
     `rates.applicable_rate_plans` says will price *this* room type on *this* line's
     arrival — the night being sold, which for a future booking is neither today nor
     the business date.

  **What may be changed is `editability`, and controls the server would refuse are
  hidden rather than shown and failed.** Add, remove, change-room-type and
  change-rate-plan are draft-like only — the controller answers "cancel and rebook
  instead" past that, because they change what availability counted and what the
  guest was quoted — so once the booking holds inventory those buttons are not on
  screen. Removing the last line is never offered: the service keeps a reservation to
  at least one room and points at cancellation. None of that is re-derived here;
  every gate is a flag the server sent, and every operation is re-checked under a
  lock on arrival.

  Cards rather than `OperationalDataTable` for the lines, deliberately. The table is
  the right tool for a board — it gives the card fallback and the row-action a11y for
  free — but a room line carries up to four verbs, a status badge, a readiness badge,
  a stay link and an expandable per-night breakdown, and the breakdown is the part
  that decides it: a disclosure that must open *under* its row is not something a
  `<table>` renders honestly, and it must not be the thing that goes missing on a
  phone. The breakdown itself is an `OperationalDataTable`, which is exactly what it
  is good at: three dense money columns with a card rendering on a narrow screen.
-->
<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <!-- The rate on every card is the server's answer, not a number typed here. -->
      <p class="max-w-2xl text-p-sm text-ink-gray-6">{{ t('page.walk_in.quote_note') }}</p>

      <!--
        A booking-level verb, not a bulk one: `add_room_line` adds exactly one room
        per call, because a row that says "three" can hold one assignment, become one
        stay and open one folio.
      -->
      <Button v-if="mayAddOrRemove" variant="subtle" @click="openAdd">
        {{ t('page.reservation.rooms.add') }}
      </Button>
    </div>

    <!-- The server's own reason, in the server's terms. Never re-derived here. -->
    <p v-if="nothingMayChange" class="text-p-sm text-ink-gray-6">
      {{ t('page.reservation.not_editable_here', { status: editability.status }) }}
    </p>

    <ul class="space-y-3" role="list" :aria-label="t('page.reservation.rooms')">
      <li v-for="view in lines" :key="view.line.name" class="rounded border border-outline-gray-1">
        <div class="flex flex-wrap items-start justify-between gap-3 border-b border-outline-gray-1 px-4 py-2">
          <div class="min-w-0">
            <p class="text-p-sm font-medium text-ink-gray-9">
              {{ view.label }} · {{ view.roomType }}
            </p>
            <!-- This line's own interval. The header's is a span across all of them. -->
            <p class="text-p-sm text-ink-gray-6">
              {{ formatDate(view.line.arrival_date) }} → {{ formatDate(view.line.departure_date) }}
            </p>
          </div>

          <!--
            The line's Stay, or nothing. `reservation_status` is not a per-line fact
            and is never shown; a line with no stay carries no badge at all.
          -->
          <Badge
            v-if="view.stayStatus"
            variant="subtle"
            :theme="stayStatusTheme(view.stayStatus)"
            :label="view.stayStatus"
          />
        </div>

        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.reservations.nights') }}</dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ view.line.nights }}</dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.guests.occupancy') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ view.occupancy }}</dd>
          </div>

          <div v-if="view.extraBeds" class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.rooms.extra_beds') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ view.extraBeds }}</dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation.rooms.rate_plan') }}
            </dt>
            <dd class="mt-0.5 text-p-sm text-ink-gray-8">{{ view.ratePlan || '—' }}</dd>
          </div>

          <!--
            The room. Which room that is depends on whether a Stay owns the line, and
            whether the caller was given Hotel Room to read — see the header comment.
          -->
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t(view.roomLabelKey) }}</dt>
            <dd class="mt-0.5 space-y-1 text-p-sm text-ink-gray-8">
              <p>{{ view.room || t('page.arrivals.no_room_yet') }}</p>

              <!-- Only where the room's condition was actually disclosed. -->
              <div v-if="view.readiness" class="flex flex-wrap gap-1">
                <Badge
                  variant="subtle"
                  :theme="view.readiness.ready ? 'green' : 'orange'"
                  :label="view.readiness.ready ? t('page.arrivals.ready') : t('page.arrivals.not_ready')"
                />
                <Badge
                  v-if="view.housekeeping"
                  variant="subtle"
                  :theme="statusTheme(view.housekeeping)"
                  :label="view.housekeeping"
                />
                <Badge
                  v-if="view.occupancyStatus"
                  variant="subtle"
                  :theme="statusTheme(view.occupancyStatus)"
                  :label="view.occupancyStatus"
                />
              </div>
            </dd>
          </div>

          <!--
            Labelled as an average, and never as "the rate": it is total/nights
            including every supplement, so it equals no actual night on a stay with an
            uplift or a free night. The nights themselves are one click below.
          -->
          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation_new.average_nightly_rate') }}
            </dt>
            <dd class="mt-0.5 text-p-sm">
              <MoneyDisplay :value="view.line.room_rate ?? null" :currency="currency" />
            </dd>
          </div>

          <div class="min-w-0">
            <dt class="text-xs uppercase tracking-wide text-ink-gray-5">
              {{ t('page.reservation_new.total_per_room') }}
            </dt>
            <dd class="mt-0.5 text-p-sm">
              <MoneyDisplay :value="view.line.total_amount ?? null" :currency="currency" bold />
            </dd>
          </div>
        </dl>

        <p v-if="view.line.special_requests" class="border-t border-outline-gray-1 px-4 py-2 text-p-sm text-ink-gray-7">
          {{ t('page.reservation.notes.special_requests') }}: {{ view.line.special_requests }}
        </p>

        <!--
          The real per-night figures, from the rate snapshot the server stored. This
          is what makes the average above readable rather than merely qualified.
        -->
        <div v-if="view.nightlyRows.length" class="border-t border-outline-gray-1 px-4 py-2">
          <Button
            variant="ghost"
            size="sm"
            :aria-expanded="expanded[view.line.name] ? 'true' : 'false'"
            :aria-controls="`rate-breakdown-${view.line.name}`"
            @click="toggleBreakdown(view.line.name)"
          >
            {{ t('page.reservation.rate_breakdown') }}
          </Button>

          <div v-if="expanded[view.line.name]" :id="`rate-breakdown-${view.line.name}`" class="pt-2">
            <OperationalDataTable
              :columns="nightlyColumns"
              :rows="view.nightlyRows"
              row-key="name"
              :aria-label="t('page.reservation.rate_breakdown')"
              dense
            />
          </div>
        </div>

        <div
          v-if="view.actions.length || view.stay"
          class="flex flex-wrap items-center gap-2 border-t border-outline-gray-1 px-4 py-2"
          role="group"
          :aria-label="t('ui.table.row_actions', { row: view.label })"
        >
          <Button
            v-for="action in view.actions"
            :key="action.key"
            size="sm"
            variant="subtle"
            :theme="action.theme || 'gray'"
            :label="action.label"
            @click="action.run()"
          />

          <!--
            The guest is in a room. Moving them is `stays.change_room`, which moves
            the folio with them, so the verb stays where it belongs.
          -->
          <router-link
            v-if="view.stay"
            class="inline-flex text-p-sm text-ink-blue-3 hover:underline"
            :to="{ name: 'Stay', params: { id: view.stay } }"
          >
            {{ t('page.in_house.action.open_stay') }}
          </router-link>
        </div>
      </li>
    </ul>

    <!-- Per line, and only ever the line it was opened on. -->
    <ChangeLineDatesDialog
      v-model="datesOpen"
      :reservation="reservation.name"
      :line="activeLine"
      :is-holding="Boolean(editability.is_holding)"
      @changed="onChanged(t('page.reservation.rooms.dates_changed'))"
    />

    <!--
      A different room type for one line, while the booking is still a working
      draft. The server drops the line's assignment (a physical room belongs to one
      type) and re-prices it, so nothing here computes a rate or keeps a room.
    -->
    <Dialog v-model="typeOpen" :options="{ title: t('page.reservation.rooms.change_room_type'), size: 'md' }">
      <template #body-content>
        <div v-if="activeLine" class="space-y-4">
          <p class="text-p-sm text-ink-gray-8">
            {{ t('page.reservation.rooms.line', { idx: activeLine.idx }) }} ·
            {{ activeLine.room_type_name || activeLine.room_type }}
          </p>
          <p class="text-p-sm text-ink-gray-6">
            {{ formatDate(activeLine.arrival_date) }} → {{ formatDate(activeLine.departure_date) }}
          </p>

          <!--
            A physical room belongs to one room type, so the service drops this
            line's assignment rather than promising a standard room to a suite
            booking. Said before the change, because choosing the room again is the
            desk's job and a VIP's usual room is not something to lose quietly.
          -->
          <div
            v-if="activeLine.assigned_room"
            class="rounded border border-outline-amber-1 bg-surface-amber-1 p-3 text-p-sm text-ink-amber-3"
          >
            {{ t('page.reservation.rooms.room_type_releases_room') }}
          </div>

          <LoadingState v-if="typeSearch.loading && !typeSearch.data" />

          <EmptyState v-else-if="!typeChoices.length" :message="t('page.reservation_new.no_room_types')" />

          <div v-else class="space-y-2">
            <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.arrivals.room_type') }}</p>

            <div class="grid gap-2 sm:grid-cols-2">
              <button
                v-for="choice in typeChoices"
                :key="choice.value"
                type="button"
                class="rounded border p-3 text-start transition-colors"
                :class="
                  typeForm.room_type === choice.value
                    ? 'border-outline-gray-4 bg-surface-gray-2'
                    : 'border-outline-gray-1 hover:bg-surface-gray-1'
                "
                :aria-pressed="typeForm.room_type === choice.value ? 'true' : 'false'"
                @click="typeForm.room_type = choice.value"
              >
                <p class="font-medium text-ink-gray-9">{{ choice.name }}</p>
                <!-- The availability service's own count and its own verdict. -->
                <p class="mt-0.5 text-p-sm" :class="choice.bookable ? 'text-ink-green-3' : 'text-ink-red-3'">
                  {{ choice.availability }}
                </p>
              </button>
            </div>
          </div>

          <ErrorMessage :message="typeError" />

          <div class="flex flex-wrap justify-end gap-2">
            <Button variant="subtle" @click="typeOpen = false">{{ t('common.cancel') }}</Button>
            <Button
              variant="solid"
              :loading="busy === 'type'"
              :disabled="!typeForm.room_type || busy === 'type'"
              @click="submitRoomType"
            >
              {{ t('page.reservation.rooms.change_room_type') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>

    <!--
      A different rate plan for one line, while the booking is still a working draft.
      The plan is the whole of the choice: there is no rate parameter here, in
      `set_line_rate_plan` or in the service beneath it — `price_reservation` asks
      `get_rate_breakdown` what the plan costs for these nights and this occupancy,
      and whatever anyone believed the nightly figure to be is overwritten by the
      answer. So no rate is shown, offered or computed in this dialog; the card's
      figures change when the aggregate is re-read.

      The list is the *applicable* plans, not every plan in the property: it is asked
      for this line's room type and its arrival — the night being priced, which for a
      future booking is neither today nor the business date.
    -->
    <Dialog v-model="planOpen" :options="{ title: t('page.reservation.rooms.change_rate_plan'), size: 'md' }">
      <template #body-content>
        <div v-if="activeLine" class="space-y-4">
          <p class="text-p-sm text-ink-gray-8">
            {{ t('page.reservation.rooms.line', { idx: activeLine.idx }) }} ·
            {{ activeLine.room_type_name || activeLine.room_type }}
          </p>
          <p class="text-p-sm text-ink-gray-6">{{ t('page.reservation.rooms.rate_plan_hint') }}</p>

          <LoadingState v-if="plans.loading && !plans.data" />

          <!-- The server found none. Not an error, and not an empty picker. -->
          <EmptyState v-else-if="!planChoices.length" :message="t('page.reservation.rooms.rate_plan_none')" />

          <div v-else class="grid gap-2 sm:grid-cols-2">
            <button
              v-for="choice in planChoices"
              :key="choice.value"
              type="button"
              class="rounded border p-3 text-start transition-colors"
              :class="
                planForm.rate_plan === choice.value
                  ? 'border-outline-gray-4 bg-surface-gray-2'
                  : 'border-outline-gray-1 hover:bg-surface-gray-1'
              "
              :aria-pressed="planForm.rate_plan === choice.value ? 'true' : 'false'"
              @click="planForm.rate_plan = choice.value"
            >
              <!-- The plan's own name. The docname is a code and is not shown. -->
              <p class="font-medium text-ink-gray-9">{{ choice.name }}</p>
              <p v-if="choice.rate_type" class="mt-0.5 text-p-sm text-ink-gray-6">{{ choice.rate_type }}</p>
            </button>
          </div>

          <ErrorMessage :message="planError" />

          <div class="flex flex-wrap justify-end gap-2">
            <Button variant="subtle" @click="planOpen = false">{{ t('common.cancel') }}</Button>
            <Button
              variant="solid"
              :loading="busy === 'plan'"
              :disabled="!planForm.rate_plan || busy === 'plan'"
              @click="submitRatePlan"
            >
              {{ t('page.reservation.rooms.change_rate_plan') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>

    <!--
      One more room on the booking. The dates default to the booking's own interval
      and are the agent's to change; availability for them is the server's answer.
    -->
    <Dialog v-model="addOpen" :options="{ title: t('page.reservation.rooms.add'), size: 'lg' }">
      <template #body-content>
        <div class="space-y-4">
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <FormControl v-model="addForm.arrival" type="date" :label="t('page.reservations.arrival')" />
            <FormControl v-model="addForm.departure" type="date" :label="t('page.reservations.departure')" />
            <FormControl
              v-model.number="addForm.adults"
              type="number"
              min="1"
              :label="t('page.reservation_new.adults')"
            />
            <FormControl
              v-model.number="addForm.children"
              type="number"
              min="0"
              :label="t('page.reservation_new.children')"
            />
          </div>

          <Button variant="subtle" :loading="addSearch.loading" @click="searchForAdd">
            {{ t('page.reservation.rooms.availability') }}
          </Button>

          <LoadingState v-if="addSearch.loading && !addSearch.data" />

          <EmptyState
            v-else-if="addSearch.data && !addChoices.length"
            :message="t('page.reservation_new.no_room_types')"
          />

          <div v-else-if="addChoices.length" class="space-y-2">
            <p class="text-xs uppercase tracking-wide text-ink-gray-5">{{ t('page.arrivals.room_type') }}</p>

            <div class="grid gap-2 sm:grid-cols-2">
              <button
                v-for="choice in addChoices"
                :key="choice.value"
                type="button"
                class="rounded border p-3 text-start transition-colors"
                :class="
                  addForm.room_type === choice.value
                    ? 'border-outline-gray-4 bg-surface-gray-2'
                    : 'border-outline-gray-1 hover:bg-surface-gray-1'
                "
                :aria-pressed="addForm.room_type === choice.value ? 'true' : 'false'"
                @click="addForm.room_type = choice.value"
              >
                <p class="font-medium text-ink-gray-9">{{ choice.name }}</p>
                <p class="mt-0.5 text-p-sm" :class="choice.bookable ? 'text-ink-green-3' : 'text-ink-red-3'">
                  {{ choice.availability }}
                </p>
              </button>
            </div>
          </div>

          <ErrorMessage :message="addError" />

          <div class="flex flex-wrap justify-end gap-2">
            <Button variant="subtle" @click="addOpen = false">{{ t('common.cancel') }}</Button>
            <Button variant="solid" :loading="busy === 'add'" :disabled="!canAdd" @click="submitAdd">
              {{ t('page.reservation.rooms.add') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>

    <!--
      Removing a room is not undoable and takes its money with it, so the line is
      named and its amount stated before the verb is offered.
    -->
    <Dialog v-model="removeOpen" :options="{ title: t('page.reservation.rooms.remove'), size: 'md' }">
      <template #body-content>
        <div v-if="activeLine" class="space-y-4">
          <p class="text-p-sm text-ink-gray-8">
            {{ t('page.reservation.rooms.line', { idx: activeLine.idx }) }} ·
            {{ activeLine.room_type_name || activeLine.room_type }}
          </p>
          <p class="text-p-sm text-ink-gray-6">
            {{ formatDate(activeLine.arrival_date) }} → {{ formatDate(activeLine.departure_date) }}
          </p>
          <p class="text-p-sm">
            {{ t('page.reservation_new.total_per_room') }}:
            <MoneyDisplay :value="activeLine.total_amount ?? null" :currency="currency" bold />
          </p>

          <ErrorMessage :message="removeError" />

          <div class="flex flex-wrap justify-end gap-2">
            <Button variant="subtle" @click="removeOpen = false">{{ t('common.cancel') }}</Button>
            <Button variant="solid" theme="red" :loading="busy === 'remove'" @click="submitRemove">
              {{ t('page.reservation.rooms.remove') }}
            </Button>
          </div>
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { Badge, Button, Dialog, ErrorMessage, FormControl, toast } from 'frappe-ui'
import { computed, reactive, ref } from 'vue'

import MoneyDisplay from '@/components/operational/MoneyDisplay.vue'
import OperationalDataTable from '@/components/operational/OperationalDataTable.vue'
import ChangeLineDatesDialog from '@/components/reservation/ChangeLineDatesDialog.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import LoadingState from '@/components/states/LoadingState.vue'
import { apiResource } from '@/resources'
import { availabilitySearchResource } from '@/resources/availability'
import { FRONT_DESK_ROLES } from '@/resources/frontOffice'
import { hasField } from '@/resources/guests'
import { statusTheme } from '@/resources/rooms'
import { stayStatusTheme } from '@/resources/stays'
import { session } from '@/stores/session'
import { normaliseError } from '@/utils/errors'
import { formatDate, toServerDate } from '@/utils/format'
import { t } from '@/utils/i18n'

const props = defineProps({
  /** The reservation's own allow-listed fields, exactly as the server sent them. */
  reservation: { type: Object, required: true },
  /** `rooms` from `get_workspace`, in the order the server sent them. */
  rooms: { type: Array, default: () => [] },
  /** The server's editability statement. The only source of what is offered. */
  editability: { type: Object, default: () => ({}) },
})

/**
 * `assign` hands the shell the line to assign — it owns `AssignRoomDialog`, which is
 * already hardened and is not reimplemented here. `changed` says a line-level
 * operation succeeded, so the whole aggregate is re-read.
 */
const emit = defineEmits(['assign', 'changed'])

const addRoom = apiResource('reservations.add_room_line')
const removeRoom = apiResource('reservations.remove_room_line')
const changeRoomType = apiResource('reservations.change_line_room_type')
const setRatePlan = apiResource('reservations.set_line_rate_plan')

/**
 * The plans that will actually price a room type on a night.
 *
 * `rates.applicable_rate_plans` asks the same service `change_line_room_type`
 * consults, so the picker offers what the server will accept rather than every plan
 * in the property — which is what the two creation screens do, and why an agent
 * there learns about an inapplicable plan from a refusal.
 */
const plans = apiResource('rates.applicable_rate_plans', { method: 'GET' })

/** Two searches, so opening one dialog cannot leave stale room types in the other. */
const typeSearch = availabilitySearchResource()
const addSearch = availabilitySearchResource()

const expanded = reactive({})
const activeLine = ref(null)
const busy = ref('')

const datesOpen = ref(false)
const typeOpen = ref(false)
const planOpen = ref(false)
const addOpen = ref(false)
const removeOpen = ref(false)

const typeError = ref('')
const planError = ref('')
const addError = ref('')
const removeError = ref('')

const typeForm = reactive({ room_type: '' })
const planForm = reactive({ rate_plan: '' })
const addForm = reactive({ arrival: '', departure: '', adults: 1, children: 0, room_type: '' })

const currency = computed(() => props.reservation.currency || null)

// --- what the server permits ------------------------------------------------

const mayAddOrRemove = computed(() => Boolean(props.editability.may_add_or_remove_rooms))
const mayChangeRoomType = computed(() => Boolean(props.editability.may_change_room_type))
const mayChangeRatePlan = computed(() => Boolean(props.editability.may_change_rate_plan))
const mayChangeDates = computed(() => Boolean(props.editability.may_change_dates))

/**
 * Assignment is the server's flag *and* a role the server will accept.
 *
 * A visibility hint only, exactly as on the boards: `services.reservations.
 * assign_room` re-checks the room under a lock and authorises the caller itself.
 * The role list is mirrored, not invented, so a role the server refuses every time
 * is not offered a button.
 */
const mayAssign = computed(
  () => Boolean(props.editability.may_assign_room) && session.hasRole(FRONT_DESK_ROLES),
)

const nothingMayChange = computed(
  () =>
    !mayAddOrRemove.value &&
    !mayChangeRoomType.value &&
    !mayChangeRatePlan.value &&
    !mayChangeDates.value &&
    !mayAssign.value,
)

// --- the lines --------------------------------------------------------------

/**
 * The stored snapshot for one night, in full.
 *
 * The three supplements are here rather than left implicit in the gap between
 * `rate` and `net_rate`: that gap is the whole reason the average above equals no
 * actual night, and a breakdown that showed only the two ends would state the
 * difference without ever explaining it.
 */
const nightlyColumns = computed(() => [
  { key: 'night', label: t('page.availability.night'), type: 'date', primary: true, nowrap: true },
  // The real rate for this night, which is what the average above is not.
  { key: 'rate', label: t('page.reservation.rooms.rate'), type: 'money' },
  { key: 'extra_adult', label: t('page.reservation.rooms.extra_adult'), type: 'money' },
  { key: 'extra_child', label: t('page.reservation.rooms.extra_child'), type: 'money' },
  { key: 'extra_bed', label: t('page.reservation.rooms.extra_bed'), type: 'money' },
  // The night's own net, supplements included. These together are why the average
  // is an average.
  { key: 'amount', label: t('page.reservation.rooms.amount'), type: 'money' },
])

const lines = computed(() => props.rooms.map((line) => buildView(line)))

/**
 * One line, as this tab renders it.
 *
 * Every disclosure question is answered here, once, so the template never has to
 * choose between a room code and a door number in a `v-if`.
 */
function buildView(line) {
  // Presence, not truthiness: the enrichment keys are absent for a caller the
  // server did not clear, and an absent key is not a `false` about the room.
  const inStay = hasField(line, 'stay')
  const stay = inStay ? line.stay : ''
  const stayRoom = hasField(line, 'stay_room') ? line.stay_room : ''
  const numberDisclosed = hasField(line, 'room_number')

  // `room_number` is looked up from `assigned_room`, so it describes that room and
  // no other. After a room move the Stay names a different room, and the number on
  // file is then the door of the room the guest left.
  const sameRoom = Boolean(stayRoom) && stayRoom === line.assigned_room
  const room = inStay
    ? (numberDisclosed && sameRoom ? line.room_number : stayRoom) || ''
    : (numberDisclosed ? line.room_number : line.assigned_room) || ''

  return {
    line,
    label: t('page.reservation.rooms.line', { idx: line.idx }),
    /**
     * The two display names, each gated on its own DocType — Room Type and Rate
     * Plan — and each falling back to the line's own column, which is a docname and
     * therefore a code. A caller who may not read the master still sees the code,
     * because it is the reservation's own field; what they never see is a code
     * presented as though it were the name.
     */
    roomType: hasField(line, 'room_type_name') ? line.room_type_name : line.room_type || '',
    ratePlan: hasField(line, 'rate_plan_name') ? line.rate_plan_name : line.rate_plan || '',
    occupancy: t('page.reservation.guests.occupancy_line', {
      adults: line.adults ?? 0,
      children: line.children ?? 0,
    }),
    // An extra bed is a fact worth stating, and it is one of the three supplements
    // inside the average. A zero is not a fact; it would only crowd the figures
    // beside it.
    extraBeds: Number(line.extra_beds) > 0 ? line.extra_beds : null,
    room,
    roomLabelKey: inStay ? 'page.stay.room' : 'page.reservation.assigned',
    /**
     * Readiness is a pre-arrival fact about the assigned room, and it is only ever
     * claimed when the server actually sent it. Suppressed once a Stay owns the
     * line: housekeeping's opinion of a room the guest may have already left is
     * not a statement about where they are now.
     */
    readiness: !inStay && hasField(line, 'room_ready') ? { ready: Boolean(line.room_ready) } : null,
    housekeeping: !inStay && hasField(line, 'housekeeping_status') ? line.housekeeping_status || '' : '',
    occupancyStatus: !inStay && hasField(line, 'occupancy_status') ? line.occupancy_status || '' : '',
    // `reservation_status` is deliberately not read: see the header comment.
    stayStatus: inStay && hasField(line, 'stay_status') ? line.stay_status || '' : '',
    stay,
    nightlyRows: nightlyRowsFor(line),
    actions: actionsFor(line, inStay),
  }
}

/** The stored rate snapshot for one line, regrouped by the server per line. */
function nightlyRowsFor(line) {
  return (line.rate_lines || []).map((night) => ({
    name: `${line.name}-${night.rate_date}`,
    night: night.rate_date,
    rate: night.rate ?? null,
    extra_adult: night.extra_adult_charge ?? null,
    extra_child: night.extra_child_charge ?? null,
    extra_bed: night.extra_bed_charge ?? null,
    amount: night.net_rate ?? null,
    currency: currency.value,
  }))
}

/**
 * The verbs offered on one line.
 *
 * Each closes over that line and nothing else, which is what makes a three-room
 * booking safe: the button on card two cannot name the line on card one.
 *
 * A line with a live Stay is offered neither assignment nor a date change. Both are
 * refused by the services for a line in a stay — `_assert_line_not_in_stay` says so
 * and names the remedy — and the remedy is the same in both cases: the Stay owns the
 * room and the interval now, and `stays.change_room`, `extend_stay` and
 * `shorten_stay` move the folio with them. The link to the stay is rendered beside
 * these, so the card still offers a way forward.
 */
function actionsFor(line, inStay) {
  const actions = []

  if (mayAssign.value && !inStay) {
    actions.push({
      key: 'assign',
      label: line.assigned_room
        ? t('page.reservation.change_assigned_room')
        : t('page.reservation.assign_room'),
      run: () => emit('assign', line),
    })
  }

  if (mayChangeDates.value && !inStay) {
    actions.push({
      key: 'dates',
      label: t('page.reservation.rooms.change_dates'),
      run: () => openDates(line),
    })
  }

  if (mayChangeRoomType.value && !inStay) {
    actions.push({
      key: 'room_type',
      label: t('page.reservation.rooms.change_room_type'),
      run: () => openRoomType(line),
    })
  }

  if (mayChangeRatePlan.value && !inStay) {
    actions.push({
      key: 'rate_plan',
      label: t('page.reservation.rooms.change_rate_plan'),
      run: () => openRatePlan(line),
    })
  }

  // A reservation keeps at least one room line; the service refuses the last one and
  // says to cancel the reservation instead, so the button is not offered for it.
  if (mayAddOrRemove.value && props.rooms.length > 1) {
    actions.push({
      key: 'remove',
      label: t('page.reservation.rooms.remove'),
      theme: 'red',
      run: () => openRemove(line),
    })
  }

  return actions
}

function toggleBreakdown(name) {
  expanded[name] = !expanded[name]
}

// --- the per-line operations ------------------------------------------------

function openDates(line) {
  activeLine.value = line
  datesOpen.value = true
}

function openRoomType(line) {
  activeLine.value = line
  typeError.value = ''
  typeForm.room_type = ''
  typeOpen.value = true

  // The line's own interval and party size, so what comes back is availability for
  // this room rather than for the booking's widest span.
  typeSearch.fetch({
    property: props.reservation.property,
    arrival: line.arrival_date,
    departure: line.departure_date,
    adults: line.adults ?? 1,
    children: line.children ?? 0,
  })
}

function openRatePlan(line) {
  activeLine.value = line
  planError.value = ''
  planForm.rate_plan = ''
  planOpen.value = true

  // The line's own room type, and its arrival as the night being priced: a plan that
  // expires before this stay begins must not be offered for it. The server falls
  // back to the property's operating day when no date is given, which is not the
  // question a future booking asks.
  plans.fetch({
    property: props.reservation.property,
    room_type: line.room_type,
    on_date: line.arrival_date,
  })
}

function openRemove(line) {
  activeLine.value = line
  removeError.value = ''
  removeOpen.value = true
}

function openAdd() {
  activeLine.value = null
  addError.value = ''
  addForm.room_type = ''
  // The booking's own interval, as the server sent it. No date is derived here.
  addForm.arrival = props.reservation.arrival_date || ''
  addForm.departure = props.reservation.departure_date || ''
  addForm.adults = 1
  addForm.children = 0
  addOpen.value = true

  searchForAdd()
}

function searchForAdd() {
  addForm.room_type = ''

  if (!addForm.arrival || !addForm.departure) return

  addSearch.fetch({
    property: props.reservation.property,
    arrival: toServerDate(addForm.arrival),
    departure: toServerDate(addForm.departure),
    adults: addForm.adults || 1,
    children: addForm.children || 0,
  })
}

/**
 * Room types as the availability service answered, in its order.
 *
 * Everything it returned is offered, with its own count and its own verdict beside
 * it: hiding what the server called unbookable would leave an agent unable to see
 * why the type they want is not there, and `check_availability` refuses it under a
 * lock regardless of what this list showed.
 */
function choicesFrom(resource, exclude = '') {
  const types = resource.data?.room_types || {}

  return Object.entries(types)
    .filter(([name]) => name !== exclude)
    .map(([name, bucket]) => ({
      value: name,
      name: bucket.room_type_name || name,
      bookable: Boolean(bucket.bookable),
      availability: bucket.bookable
        ? t('page.walk_in.min_available', { count: bucket.min_available })
        : t('page.walk_in.not_bookable'),
    }))
}

// The line's current type is left out: the service refuses "already a Deluxe", and
// offering it would be an option whose only outcome is a refusal.
const typeChoices = computed(() => choicesFrom(typeSearch, activeLine.value?.room_type || ''))
const addChoices = computed(() => choicesFrom(addSearch))

/**
 * The plans the server said apply, in the order it sent them (`display_order`).
 *
 * `rate_plan_name` is what a plan is called and `name` is its docname — a code — so
 * the name is what is offered. No currency and no figure: a plan is not a price, and
 * the price of this one is `get_rate_breakdown`'s answer after the change.
 */
const planChoices = computed(() =>
  (plans.data || []).map((plan) => ({
    value: plan.name,
    name: plan.rate_plan_name || plan.name,
    rate_type: plan.rate_type || '',
  })),
)

const canAdd = computed(
  () => Boolean(addForm.room_type && addForm.arrival && addForm.departure) && busy.value !== 'add',
)

async function submitRoomType() {
  if (!activeLine.value || !typeForm.room_type) return

  busy.value = 'type'
  typeError.value = ''

  try {
    await changeRoomType.submit({
      reservation: props.reservation.name,
      room_line: activeLine.value.name,
      room_type: typeForm.room_type,
    })

    typeOpen.value = false
    onChanged(t('page.reservation.updated'))
  } catch (error) {
    typeError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function submitRatePlan() {
  if (!activeLine.value || !planForm.rate_plan) return

  busy.value = 'plan'
  planError.value = ''

  try {
    // A plan, and nothing else. The rate is the rate service's answer to it.
    await setRatePlan.submit({
      reservation: props.reservation.name,
      room_line: activeLine.value.name,
      rate_plan: planForm.rate_plan,
    })

    planOpen.value = false
    onChanged(t('page.reservation.rooms.rate_plan_changed'))
  } catch (error) {
    planError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function submitAdd() {
  if (!canAdd.value) return

  busy.value = 'add'
  addError.value = ''

  try {
    await addRoom.submit({
      reservation: props.reservation.name,
      room_type: addForm.room_type,
      arrival: toServerDate(addForm.arrival),
      departure: toServerDate(addForm.departure),
      adults: addForm.adults || 1,
      children: addForm.children || 0,
    })

    addOpen.value = false
    onChanged(t('page.reservation.rooms.line_added'))
  } catch (error) {
    addError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

async function submitRemove() {
  if (!activeLine.value) return

  busy.value = 'remove'
  removeError.value = ''

  try {
    await removeRoom.submit({
      reservation: props.reservation.name,
      room_line: activeLine.value.name,
    })

    removeOpen.value = false
    onChanged(t('page.reservation.rooms.line_removed'))
  } catch (error) {
    removeError.value = normaliseError(error).message
  } finally {
    busy.value = ''
  }
}

/**
 * A line operation succeeded.
 *
 * The whole aggregate is re-read by the page rather than patched here: every one of
 * these operations re-derives the booking's own totals and header interval, and a
 * card updated in place would disagree with the header above it.
 */
function onChanged(message) {
  toast.success(message)
  emit('changed')
}
</script>

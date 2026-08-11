/**
 * Operation keys for mutating requests.
 *
 * The server refuses a financial mutation that does not name the operation it
 * is performing, and will not invent a name of its own. That is deliberate: it
 * used to, and because the generated key was new on every HTTP attempt, a
 * request whose response was lost was retried under a fresh identity and the
 * guest was charged twice (P2-3).
 *
 * The identity has to belong to the *user's action*, which only the client
 * knows about. One key is minted when the operator submits, kept across every
 * retry of that submission - the operator pressing the button again, an
 * automatic retry, a proxy replaying the request - and discarded only when the
 * action is definitively over, at which point the next submission is a new
 * operation and gets a new key.
 *
 * Usage:
 *
 *     const operation = useOperationKey()
 *
 *     async function submit() {
 *       await post.submit({ ..., idempotency_key: operation.current() })
 *       operation.done()        // succeeded: the next submit is a new action
 *     }
 *
 * Note what is *not* done here: the key is not derived from the form contents.
 * Two minibar waters at the same price with the same description are two
 * charges, and a content hash cannot tell them apart from one charge sent
 * twice.
 */
import { ref } from 'vue'

/** A fresh, globally unique operation key. */
export function newOperationKey(prefix = 'op') {
  const unique =
    globalThis.crypto?.randomUUID?.() ??
    // Older WebViews have no randomUUID. Two independent sources of entropy
    // are enough here: the key only has to be unique among this user's
    // in-flight operations, not unguessable.
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`

  return `${prefix}:${unique}`
}

/**
 * A key that survives retries of one action and changes when the action does.
 *
 * `current()` mints on first use and then returns the same value until
 * `done()` or `reset()`, so a retrying caller needs no bookkeeping of its own.
 */
export function useOperationKey(prefix = 'op') {
  const key = ref('')

  function current() {
    if (!key.value) key.value = newOperationKey(prefix)

    return key.value
  }

  /** The action completed. The next `current()` starts a new operation. */
  function done() {
    key.value = ''
  }

  return { current, done, reset: done }
}

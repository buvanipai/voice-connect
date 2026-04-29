# VoiceConnect — Open Work & Multi-Client Considerations

Snapshot of what's not finished and how each item plays in a multi-client setup.
Pick up from here.

---

## 1. Call forwarding to a human

**Status:** Not implemented. Inbound call goes straight to the ElevenLabs agent
(now via the native ElevenLabs ↔ Twilio phone-number integration, no TwiML proxy).
Nothing bounces the live call.

**Multi-client model:**
- Add `forward_to_number` to each client doc in Firestore (set via client Settings page).
- Two ways to use it:
  - **Escalation tool** — give the agent a `transfer_call` tool that calls Twilio REST
    to update the live call with `<Dial>{{forward_to_number}}</Dial>`. Agent decides
    when to escalate. Cleanest UX.
  - **Fallback on agent failure** — if we ever move back to a TwiML proxy, wrap
    `<Connect>` in a `<Dial>` timeout.
- Each client gets their own forwarding destination — no shared state.

**To do:**
- Schema: `forward_to_number` on client.
- UI: field on Client Settings + Admin Clients form.
- Backend: `/twilio/transfer/{call_sid}` endpoint the agent (or Twilio Function) can hit.

---

## 2. Real SMS (not WhatsApp)

**Status:** `send_whatsapp_followup` uses the `whatsapp:` prefix. "sms"/"text"/"message"
contact preferences are aliased to WhatsApp in `app/main.py:79-80`.

**Multi-client model:**
- Each client already has their own Twilio number (`client.phone_number`). SMS sends
  cleanly from that number — no cross-client leakage.
- Production US SMS requires **A2P 10DLC** (see item 3). Without it: blocked or
  heavily rate-limited.

**To do:**
- Add `send_sms_followup(to, from_number, body)` — same as WhatsApp but no prefix.
- Split `contact_preference`: `sms`, `whatsapp`, `email` as three distinct values.
- UI: let client pick which channels to offer in their agent's conversation.
- Don't conflate SMS and WhatsApp anymore.

---

## 3. A2P 10DLC registration

**Status:** Not started. Trial / sandbox messaging only. Deferred — not needed for
voice or WhatsApp.

**Multi-client model:**
- VoiceConnect registers once as the **ISV** (Independent Software Vendor) with Twilio.
  Account is now on the paid plan as Bhuvi IT Solutions Inc (EIN 47-2739181, IL).
- Each client registers as a **Brand** (their legal entity) and a **Campaign** (the
  use case — e.g. "Lead follow-up SMS").
- Without this: outbound SMS to US numbers will be filtered or rejected at scale.
- Needs EIN / business info from each client during onboarding.

**To do:**
- Register VoiceConnect as ISV in Twilio console.
- Add client-side onboarding fields: EIN, legal name, business address, website,
  message sample.
- Admin action: submit each client's Brand + Campaign via Twilio API.
- Track 10DLC status per client (`pending_brand`, `pending_campaign`, `approved`, `rejected`).
- Block SMS sending until Campaign is approved.

---

## 4. Intent saving bug

**Status:** Agent's `branch` data collection may still save as `GENERAL_INQUIRY`.
Logic in `app/main.py:_normalize_intent` falls back when the value doesn't match.

**Multi-client model:** Not multi-client-specific — code fix only.

**To do:**
- Verify ElevenLabs agent config has `branch` as a data collection field with the
  correct enum values: `JOB_SEEKER`, `US_STAFFING`, `SALES`, `GENERAL_INQUIRY`.
- Re-test with a JOB_SEEKER call. Check logs for what's actually in
  `data_collection_results["branch"]`.
- Fix either the agent prompt or the normalizer mapping.

---

## 5. Billing model

**To decide:**
- Each client's Twilio number costs ~$1.15/mo + usage. Pass to clients or bake
  into SaaS pricing.

---

## 6. Gmail credentials / app-password fallback

**Status:** OAuth flow exists per client. App-password fallback exists but needs env
vars set (`GMAIL_SENDER_EMAIL`, `GMAIL_APP_PASSWORD`) on Cloud Run for clients who
haven't connected Gmail yet.

**Multi-client model:**
- Preferred: each client connects their own Gmail → emails send from their mailbox.
- Fallback: platform mailbox sends on their behalf. Same fallback for everyone.

**To do:**
- Set Cloud Run env vars for fallback (or remove fallback if you don't want platform
  to send).
- Surface "Gmail not connected — emails will send from VoiceConnect's mailbox"
  warning on client Settings.

---

## Quick multi-client sanity check

| Concern                     | Per-client isolated? | Notes |
|----------------------------|----------------------|-------|
| Phone number                | ✅ | Each client owns a Twilio number, imported into ElevenLabs |
| ElevenLabs agent            | ✅ | Each client has a cloned agent + KB, bound to their phone |
| Caller profiles (Firestore) | ✅ | Namespaced by `client_id` |
| Gmail OAuth                 | ✅ | Refresh token stored per client |
| Follow-up templates         | ✅ | `intent_labels` + SMS templates per client |
| SMS sender                  | ✅ | Sends from client's own number |
| 10DLC registration          | ⚠️ | Per-client brand/campaign needed |
| Call forwarding target      | ❌ | Not yet modeled |

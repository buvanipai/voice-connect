# VoiceConnect — Admin User Manual

This is the guide for the **admin**. It covers everything you need to run the platform day-to-day: onboarding clients, watching call activity, handling failures, and configuring messaging.

---

## URLs

| What | URL |
|---|---|
| Dashboard (admin + client login) | https://voiceconnect-frontend-ulzhzqohga-uc.a.run.app |
| Client self-signup page | https://voiceconnect-frontend-ulzhzqohga-uc.a.run.app/signup |
| Backend API | https://voiceconnect-api-271365674375.us-central1.run.app |

---

## What VoiceConnect does

A business signs up and gets an AI phone number. When someone calls that number, an AI agent answers, has a real conversation, and collects their details. After the call, the caller gets a follow-up SMS or email. The admin oversees all of this from a single dashboard.

---

## Logging in

Go to https://voiceconnect-frontend-ulzhzqohga-uc.a.run.app and sign in with your admin email and password. You land on the **Clients** page automatically.

---

## Clients page — your main control panel

This is where you manage the full lifecycle of every business using the platform.

### What you see

- **Pending approval** — clients who signed up but haven't been provisioned yet
- **Active clients** — clients fully live with a phone number and AI agent
- **Tracked callers** — total callers across all accounts

Each row in the table shows the client's name, website, current status, their assigned phone number, usage stats, and whether they've connected their Gmail inbox.

### Onboarding a new client — step by step

1. Send the client to https://voiceconnect-frontend-ulzhzqohga-uc.a.run.app/signup to fill in their name, website URL, email, password, and optionally a preferred area code and country.
2. They appear in your Clients table with status **Pending**.
3. Click **Provision client** next to their name.
4. The platform automatically:
   - Scrapes their website and builds an AI knowledge base from it
   - Creates a dedicated AI phone agent trained on that knowledge base
   - Purchases a Twilio phone number (in their preferred area code if they provided one)
   - Wires everything together so incoming calls route to their agent
5. Status changes to **Active**. Their phone number appears in the table.
6. Tell the client: "You're live — put this number on your website."

If something goes wrong during provisioning (e.g. Twilio couldn't find a number in that area code), the status shows **Provisioning failed** with an error message underneath. Fix the underlying issue and click **Retry provisioning**.

### Deleting a client

Click **Delete account**. This removes their account from the platform. Do this only when a client cancels — it's not reversible.

---

## All Callers page

This is a cross-account view of every person who has ever called any client's number.

### Filtering

- **Client dropdown** — narrow to one client's callers, or leave on "All clients" to see everything
- **Intent dropdown** — filter by what the caller was calling about (Job Seeker, Sales, General Inquiry, etc.)

### Viewing a caller

Click any row to open the caller detail panel on the right. It shows:

- Phone number and name
- When they first called and when they last called
- A card for each intent type they've called about, with all the information collected (name, email, role interest, years of experience, etc.) and a plain-English summary of that conversation

---

## Settings page

Platform-wide default SMS messages. These apply to all clients who haven't written their own custom message.

- **Job seeker follow-up** — the SMS sent after a job seeker call
- **Sales lead follow-up** — the SMS sent after a sales inquiry call

Write these in plain text. Clients can override them from their own Settings page.

---

## Failed Notifications page

Every time a follow-up SMS or email couldn't be delivered, it appears here. Columns:

- **Timestamp** — when the failure happened
- **Caller** — the phone number that was supposed to receive the message
- **Channel** — SMS or email
- **Reason** — the exact error (e.g. "no email address was available", "Twilio error 21211")

Use this page to spot patterns — if a lot of email failures are happening, clients may not have connected their Gmail. If SMS is failing, check Twilio account status.

---

## What clients see on their end

Once provisioned, a client logs in at https://voiceconnect-frontend-ulzhzqohga-uc.a.run.app and sees:

- Their assigned phone number front and centre
- A table of every caller with names, intents, and last call time
- A Settings page where they can write their own follow-up SMS copy and connect their Gmail so emails come from their own inbox

Clients can log in any time to review caller activity. They cannot see other clients' data.

---

## The call flow, in plain English

1. Someone calls the client's number
2. The AI agent answers and has a natural conversation, pulling answers from the client's website
3. The AI collects whatever's relevant (name, email, job type, etc.) depending on why the caller is calling
4. After the call ends, the system saves the caller's profile
5. If the caller asked for a follow-up (by SMS or email), it gets sent immediately
6. The caller appears in the client's Callers table within seconds

---

## Common situations

**"A client says their number isn't working"**
Check their status on the Clients page. If it says anything other than Active, provisioning didn't complete. Retry or re-provision.

**"A caller isn't showing up after a call"**
The post-call webhook from ElevenLabs may have failed. Check Cloud Run logs. The caller profile only saves after the call ends and the webhook fires.

**"Follow-ups aren't being sent"**
Check the Failed Notifications page. The most common reasons: caller didn't provide an email, client hasn't connected Gmail, or Twilio SMS credit is low.

**"A client wants to change their follow-up message"**
They can do it themselves from their Settings page. No action needed from you.

**"A client wants a number in a specific area code"**
They set this at signup. If they already signed up without one, delete and re-create the account, or manually update the area_code field in Firestore before provisioning.

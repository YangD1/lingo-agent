# Demo script

[简体中文](demo.md)

A 5–10 minute walk through Lingo Agent, using a demo account with about two weeks of learning behind it. Each step says **what to say**, **what to click** and **what you should see**. The "you should see" lines also work as an end-to-end checklist.

## Setup (once, before the demo)

1. Start the stack and import the word list as in the README's Quick start: `make env`, `make up`, `make vocab-import`, `make sentences-import`, `make senses-import`.
2. Create the demo account:

   ```bash
   make demo-seed ARGS='--password your-demo-password --lang en'  # explanations in English
   make demo-seed ARGS='--password your-demo-password'            # explanations in Chinese
   ```

   This creates `demo@lingo.example.com`. If the account already exists, it is deleted with all its data and created again. No other account is read or changed, and no model is called. Leave out `--password` and a random one is printed.
3. Sign in as the demo account and add a connection under **Settings → Model connections**, because the demo account has no model. Alternatively, invite it from a main account so it can use that account's models.
4. Optional: the call needs a connection with realtime voice. Shadowing scores need speech-to-text or a pronunciation service. Without them you can still give the demo; just skip those parts of step 7.

**The demo learner:** Lin is a product manager at a travel-app company. Later this year Lin will give a short talk at a conference in Singapore. Lin likes old films, hiking and coffee, and studies 20 minutes a day. Lin keeps mixing up the present perfect and the past simple. Lin's memories say Lin wants explanations mostly in Chinese and examples in English; `--lang` sets the profile's explanation language. The account has about two weeks of history: a placement test, daily word reviews, two practice sets, a piece of writing, an article, a speaking session and a diagnosis. Every number comes from the real engines; only the dates are set in the past. **There is no chat history.** Conversations happen live during the demo, with a real model.

## The walk

### 1. Dashboard (about 1 min)

- **Say:** "This is two weeks in. The level and vocabulary size come from the placement test and keep updating as you learn."
- **Click:** **Dashboard** in the sidebar.
- **You should see:**
  - [ ] CEFR level **B1**, about 3,500 words, a 10-day streak, and the number of words due today.
  - [ ] **Today's plan**: reviews, grammar practice, new words and more, each with a time estimate, about 20 minutes in all. Adjust or toggle the items, then click **Confirm plan**. After that, each item ticks itself off as it gets done.
  - [ ] Further down: the study calendar, grammar mastery and common mistakes.

### 2. Learner model (about 1 min)

- **Say:** "No language model scores mastery. BKT and Elo work it out from each piece of evidence, and every number can be opened to see why."
- **Click:** **Learner model**, then open "Present perfect vs past simple".
- **You should see:**
  - [ ] **Grammar mastery**: "Present perfect vs past simple" is weak, "Comparative adjectives" is being consolidated, and "be going to for plans and predictions" is learned.
  - [ ] An opened point shows its mistakes, correct uses, and where each piece of evidence came from: the placement test, practice or chat. Each piece can be deleted, and mastery is then worked out again.
  - [ ] **Tutor's diagnosis**: the likely causes behind repeated mistakes, with the mistakes it cites. If the diagnosis is wrong, click "This diagnosis is wrong" to delete it.
  - [ ] **Skill estimates**, **Shadowing** and **My AI use**.
- **Then click:** **Memory**.
- **You should see:**
  - [ ] **Your profile** and **Things the tutor remembers**: travel-app PM, the Singapore conference, weekend hikes near Hangzhou, watching *Roman Holiday*… Each one can be edited and deleted.

### 3. Chat (about 2 min)

- **Say:** "Let's make the mistake Lin usually makes and see what the tutor does."
- **Click:** **Chat**, then send these two messages:
  1. `I have been to Hangzhou last month with my family.`
  2. `We walked around West Lake and I have tried the Longjing tea.`
- **You should see:**
  - [ ] The tutor keeps the conversation going. It also points out that a finished time like "last month" takes the past simple, explained in the explanation language.
  - [ ] The reply brings up something it remembers, such as the hikes or the conference.
  - [ ] Under the reply, **What the tutor did**: memories read, grammar mistakes marked, and so on. Expand it to see which memories and mistakes, with links to "Manage memories" and the learner model.
  - [ ] Back in the **Learner model**, the new mistakes now show up as evidence under "Present perfect vs past simple". Memory work runs in the background without slowing the reply, so give it a few seconds.

### 4. Vocabulary (about 1 min)

- **Say:** "FSRS decides when each word comes back."
- **Click:** **Vocabulary**, then **Start**, and review a few cards.
- **You should see:**
  - [ ] How many words are due and how many new words are left; the current word book is the Oxford 3000.
  - [ ] Cards with phonetics, Chinese meanings, English senses (Simple English Wiktionary) and Tatoeba example sentences (with translations where there are any). The microphone by an example starts shadowing.
  - [ ] Back on the **Dashboard**, fewer words are due.

### 5. Reading (about 1 min)

- **Say:** "News is rewritten for the learner's level and comes with comprehension questions."
- **Click:** **Reading**, then open "Volunteers plant a million trees along an old railway".
- **You should see:**
  - [ ] The B1 version, "A million new trees on an old railway", and a switch to the original.
  - [ ] Words due for review today are highlighted, and words above the learner's level are underlined.
  - [ ] Comprehension questions that quote the text, and **Ask the tutor about this article**.

### 6. Grammar practice (about 1 min)

- **Say:** "One model writes the questions and another checks them. Questions that fail the check are rewritten or replaced from the question bank."
- **Click:** **Grammar practice**, then **Start a set**, and answer two or three questions.
- **You should see:**
  - [ ] Progress stages such as "Writing questions…" and "Checking questions…". The questions centre on weak points, with some mastered points mixed in.
  - [ ] An explanation right after each answer. "Rewrite a sentence you got wrong" questions use Lin's real mistakes.
  - [ ] The two earlier sets under **Recent sets**. When a set is finished, its results show how each grammar point's mastery changed.

### 7. Speaking and shadowing (about 1–2 min)

- **Click:** **Speaking**, then open the self-introduction under "Past practice".
- **You should see:**
  - [ ] Its summary: what went well, mistakes and fixes, more natural ways to say it, things to try next time (each with **Add to word list**), and **Practise again**.
- **Optional (needs realtime voice):** click **Call** and pick "Introducing yourself". Say a sentence or two, then ask the tutor what a word means and to add it to your word list.
  - [ ] The call shows the tool steps (the word looked up, then added to your word list), and Undo takes the word off the list again.
  - [ ] When the tutor thinks you could stop, it asks "Hang up?". After hanging up you get the transcript and a summary.
- **Optional (shadowing):** click the microphone next to a tutor reply in chat and read it aloud.
  - [ ] The reading shows up under **Learner model → Shadowing**. Without a pronunciation service it is marked "rough".

### 8. My tutor and the desk pet (about 30 s)

- **Click:** **My tutor**.
- **You should see:**
  - [ ] The tutor's looks (name, outfit, fur, animation), the desk pet switch and the conversation model.
  - [ ] The desk pet in the corner of every page. Tap it to chat with the tutor right there.

### 9. Settings: usage and members (about 1 min)

- **Say:** "Each user brings their own model keys, which are stored encrypted. Every AI call is recorded."
- **Click:** **Settings → Usage**, then **Settings → Members**.
- **You should see:**
  - [ ] Usage: totals, a daily chart, and calls and tokens per use and per model, including the ones made during this demo. After you enter prices, it estimates costs.
  - [ ] Members: invite links, and daily and monthly quotas per member (empty means no cap, 0 turns it off). Members never see your keys; you see only their usage.
  - [ ] An AI badge on every entry point that calls a model. It tells you before you click that AI is used, and roughly how many tokens each use takes.

## Full walkthrough with a new account

The demo account skips sign-up and the placement test. For the full end-to-end check (the end-to-end item under "验证方式" in PLAN), sign up a new account and go through these steps in order:

- [ ] Sign up, then add a model connection in Settings.
- [ ] **Placement test** (about 10 minutes): its result page gives a level and an estimated vocabulary size, and you can talk the result over with the tutor right there.
- [ ] **Chat**: tell the tutor something about yourself, such as your job or a hobby. **What the tutor did** shows one or more memories saved, and they also appear on the **Memory** page.
- [ ] Start a new conversation and ask "Do you remember what I do for work?". The tutor should bring up what it saved in the first conversation.
- [ ] **Vocabulary**: choose a word book, learn a few new words and review them.
- [ ] **Reading**: open an article, wait for the version for your level, and answer the questions.
- [ ] **Shadowing**: click the microphone by a paragraph and read it aloud. The reading shows up under **Learner model → Shadowing**.

## Reset

Run `make demo-seed` again to put the demo account back the way it was. The conversations and records made during the demo are deleted.

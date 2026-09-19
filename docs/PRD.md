# Polytale — Scenario-Based Language Learning Game · Product Requirements

Version 0.3 · September 19, 2026 · VTHacks 14

This document covers the product concept, what we are building this weekend, the learning mechanic, and the technical approach. Section 11 lists the open decisions the team still needs to make.

## 1. Product Concept

The product is an AI-driven, scenario-based language learning game. The learner is placed in a concrete situation, hears the target language, observes the scene, and completes tasks. Meaning is inferred from context rather than supplied through translation or vocabulary lists.

Two comparisons are worth making, and both come up in the demo pitch.

Compared to Duolingo-style apps, this product gives the learner a continuous scene and a continuous conversation. Content is not delivered as isolated exercises.

Compared to asking a general-purpose chat model to role-play a character, this product never translates and the character never accommodates the learner's native language. The learner has to use the target language to get something done, and success is expressed as a change in the state of the scene.

There is a precedent worth knowing: *Chants of Sennaar*, a commercial game built around inferring a constructed language, which was well received. The difference here is that we teach a real language, and the character's dialogue is generated live by an LLM, so it can respond to broken or incomplete input. That last point is also our answer to "why does this need AI at all?"

## 2. Scope for This Weekend

The full product would support multiple languages, learning-path planning, difficulty management, and open-ended scene customization. None of that is in scope for the hackathon. We mention it only when describing the longer-term vision.

What we are building:

- One language, locked for the demo. No language switching.
- One main scene, built end to end: entry, bounded customization, progressive learning, end-of-round summary.
- A second scene, built far enough to be entered, with a background, an opening exchange, and enough content to carry the recall moment.

The delivery target: within four minutes, a judge should personally experience going from not understanding a word to inferring its meaning, and then see one instance of unprompted recall.

## 3. Design Principles

These five principles came out of earlier design discussion. Changing any of them affects the whole experience, so re-evaluate before changing one.

**Implicit acquisition, not explicit instruction.** No translation, no grammar pop-ups. The character speaks the target language while the scene highlights the matching object or performs the matching action. The learner infers the meaning.

**Everything in a scene must be showable on screen.** The only clue a learner has is what they can see. That restricts us to concrete nouns and simple imperatives: take, give, open, this one, how much. Abstract concepts give the learner nothing to infer from and stay out of scope. This principle also does useful work as a scope limiter.

**No native-language translation.** Target-language subtitles should be shown, because they help the learner find word boundaries. Native-language subtitles should not. For languages with complex writing systems, add romanization to assist segmentation, but never gloss the meaning.

**A change in scene state is the evidence that learning happened.** When the learner does the right thing, the world responds: the door opens, the item is handed over. This replaces scoring and quizzes.

**Cross-scene recall is the core mechanic.** A word learned in one scene reappears in a later scene with no prompt at all, and the learner has to produce it from memory. This is our concrete answer to fragmented learning, and it is the one moment in the demo that proves learning occurred without us having to explain anything.

## 4. Learning and Mastery Mechanic

This section is the core product logic and the part where we most need to control scope.

### 4.1 How mastery is measured

Mastery falls out of gameplay directly. No separate quiz UI is needed. The measure is how much help the learner needed before taking the correct action.

- Correct action on first hearing → **mastered**
- Needed a repeat from the character or an object highlight → **shaky**
- Needed an intent hint → **not learned**
- Wrong action or skipped → **not learned**

### 4.2 The vocabulary record

Each target item stores four things: how many times it has appeared, the result of each appearance, the most recent scene it appeared in, and its current state. Current state is one of three values: not encountered, shaky, mastered.

Everything in the long-term vision — learning plans, difficulty management, review scheduling — is a query against this table. We are not building those queries this weekend.

### 4.3 When to show the learner the target word list

One option is to show the learner, at the start of a scene, which words and phrases they are expected to master. This conflicts with the implicit acquisition principle in Section 3: if the learner knows the answers going in, the inference step is bypassed.

We recommend showing the list at the end of the scene instead. The system knows the target list from the start but does not reveal it. The end-of-round summary screen shows the list for the first time, annotated with how well each item was handled.

Three reasons for this ordering. It preserves the inference. It turns the summary screen into its own beat in the demo, making the learning outcome visible. And "you just learned seven words without noticing" is more convincing than "here are seven words, go learn them."

If we want a sense of progress at the start of a scene, we can show the *count* of target items without showing their content.

### 4.4 Recall rules

When composing a later scene, read the vocabulary record and vary presentation by state.

- Items marked **mastered**: reappear with no prompt. This is the highlight of the demo.
- Items marked **shaky**: reappear with a highlight, effectively a second teaching pass.
- Items **not yet encountered**: introduced on the normal beat structure.

Because interactive objects are pre-made (see 7.2), the object set in Scene 2 has to overlap with Scene 1, or recall has nothing to attach to. Plan the two word lists together.

### 4.5 What we build this weekend

In scope: the vocabulary record table, held in memory or a simple database; the three states and the rules in 4.1; the end-of-round summary screen; Scene 2 injecting recall items based on the record.

Out of scope: user accounts and cross-device persistence; spaced repetition scheduling; automatic difficulty adjustment; learning plan generation; any analytics dashboard.

The reasoning behind that line: the only parts a judge can see are the summary screen and the recall moment. Everything else is backend plumbing that can be simplified without any visible difference, and building it properly would eat a large share of our time.

### 4.6 Dynamic scene generation (direction, not scope)

This capability is not in scope for the hackathon. It is recorded here as a product direction.

In the current design, Scene 2 is hand-composed based on the record produced by Scene 1. That approach generalizes: after the learner finishes a room, the system reads the vocabulary record and this round's performance, and generates the next room — which scene, which objects appear, which items to target, what the task is. Learning becomes a chain that keeps extending based on what the learner has and has not absorbed.

If we build this, three layers need to be separated by when they are generated.

**Character dialogue and reactions** are generated at runtime. This already works in the current design.

**Scene composition** — which room, which objects, which target items, what task — can be decided by the model at runtime, provided the objects and backgrounds are drawn from an existing asset library. The model composes; it does not draw.

**The visual assets themselves** are not suitable for runtime generation. See 7.2: generated images cannot reliably isolate a single unambiguous target.

Given that split, the part of "dynamic narrative generation" that is actually reachable during the hackathon is the composition layer. If the main scene and the recall moment finish early and we have time left, we can switch Scene 2 to model-composed from the asset library. This is a stretch goal, not a commitment.

## 5. Scene Design

### 5.1 Choosing the main scene

Candidates: classroom, meeting, bar. Evaluated against the "showable on screen" principle in Section 3:

**Bar or café — recommended.** Ordering, pointing at items, paying, asking for the check are all physically demonstrable, and the vocabulary is naturally concrete.

**Classroom — usable with care.** Only if we stay on physical actions: hand in the assignment, turn to a page, sit down, look at what's on the board. The moment it drifts into discussing a concept, it violates the principle. Pairing it with a strict-teacher persona does show off customization well.

**Meeting — not recommended for the demo.** Agreeing, disagreeing, scheduling — almost none of it gives the learner a visual clue to infer from. Keep it in the vision.

### 5.2 What a scene contains

Using the bar as the example, a scene has three layers.

**Background layer**: atmosphere art, AI-generated, batch-produced and stored during development. Carries no meaning.

**Interactive object layer**: a fixed set of props — a few drinks, a menu, money, a glass — composited on top of the background. This layer carries the meaning, and highlighting is controlled by our code.

**Character**: the bartender. Dialogue generated by the LLM, persona customizable.

**Target list**: 8–12 words or phrases, defined by us. Spanish example: *cerveza* (beer), *agua* (water), *cuánto* (how much), *dinero* (money), *esto* (this one), *dame* (give me), *cuenta* (the check). Demo language is still undecided; this is illustrative only.

### 5.3 Difficulty beats within a scene

A single scene is divided into beats, with assistance decreasing as it goes.

**Beat 1** — the character says the target word while the object is highlighted *and* the matching action is performed. The learner can infer it with almost no effort. This builds confidence.

**Beat 2** — the word plus the highlight, but no action.

**Beat 3** — the word alone, no highlight. The learner locates it using context built up earlier.

Cross-scene recall happens in Scene 2; rules in 4.4.

## 6. Customization Scope

In the long-term vision, learners can freely customize scenes — a strict teacher, an absurd setting, whatever they want. Fully open-ended scene generation is not viable this weekend, for two reasons: output and latency are both unpredictable, and AI-generated scenes produce ambiguous interactive objects that the learner cannot reliably infer from.

We are going with bounded customization instead.

The learner can choose: a scene from a set of presets, and the character's persona and difficulty (friendly to strict, normal to unhinged).

Customization affects only how the character speaks — tone, patience, how often they repeat themselves — implemented through the prompt. The scene's objects and target list do not change. A strict teacher and a friendly teacher teach the same items.

This still gives us a live demo moment: change the persona in front of the judge and the character's behavior shifts immediately, while scene content stays under our control.

## 7. Technical Approach

### 7.1 Audio

We are going with text input, text output, and TTS playback. The learner types, the character responds in text, and the character's text is spoken through a voice model. Voice input and real-time speech-to-speech are listed as future extensions and are not being built this weekend.

This satisfies the ElevenLabs track while avoiding the latency risk of a full bidirectional voice loop. Chaining speech recognition, model generation, and speech synthesis means any one of the three can stall and break conversational rhythm. End-to-end latency control there is hard, and we are not targeting it.

### 7.2 Visuals

Visuals are split into a background layer and an interactive object layer.

For the demo, both backgrounds and interactive objects are pre-made assets. The assets are AI-generated, produced and stored during development, and loaded at runtime. No image generation happens at runtime.

Runtime generation shows up in the character's dialogue and in persona customization. Describe it to judges exactly that way: the art is AI-generated and pre-produced, the conversation is live.

**Highlighting is controlled by our code, never by the generation model.** A generation model cannot reliably produce an image where exactly one target stands out and nothing else is ambiguous. Once the image is ambiguous, inference stops working and the core mechanic fails.

### 7.3 Character model constraints

The character's system prompt needs to enforce all of the following.

- Output only the target language. Never output the learner's native language.
- React to the learner's *intent*, not to the language they used. If the learner writes in their native language, the character signals incomprehension, points at an object, or repeats itself.
- Accept incomplete input. If intent is recoverable, advance the scene.
- Never explain grammar, never translate, never admit to being an AI, never break character.
- Stay within the current scene's objects and target list.

These constraints need testing before judging. One of us should play an adversarial player: write in English, swear at it, ask "you're an AI, right?", ask it to translate. Judges are likely to try the same things at the table.

## 8. Build Scope and Cut Order

### 8.1 Must finish

The main scene end to end: background, spoken character dialogue, object highlighting, scene state changes, end-of-round summary screen.

The cross-scene recall moment. This is the only evidence in the demo that learning actually happened.

### 8.2 Can stay minimal

Scene 2 only needs to be enterable, with a background, an opening exchange, and enough to carry recall.

### 8.3 Cut order if we fall behind

1. Runtime image generation
2. Voice input
3. Number of scenes
4. Customization options, downgraded to one or two fixed personas

Several scenes all sitting half-finished will hurt us on completeness scoring. Judges only watch the one scene we demo.

## 9. Demo Plan

### 9.1 Opening line

Judges go table to table, so the opening has to be short and repeatable. Suggested:

> "Every AI speaking-practice product out there treats each conversation as disconnected. We make a phrase you picked up in one scene come back in a different scene with no hints. Put the headphones on — you don't need to know any of this language to try it."

### 9.2 Demo flow

1. Hand the judge the headphones and let them personally go from hearing the target language to clicking the right object. 30–60 seconds. **They operate it, not us.**
2. Change the character persona live and show the tone shift immediately. About 10 seconds.
3. Move to Scene 2 and let them hit an unprompted recall item.
4. Close on why this needs AI: the character handles broken input and reacts live.

### 9.3 Questions we should expect

**"How is this different from role-playing with ChatGPT?"** It never translates and never accommodates your native language. Demonstrate live by typing English at the character.

**"Isn't this Chants of Sennaar?"** That game teaches a constructed language. We teach a real one, and our characters generate dialogue live.

**"How do you know the learner actually learned anything?"** The cross-scene unprompted recall moment.

**"What about voice latency?"** We use text input plus TTS playback specifically to avoid a bidirectional voice loop.

### 9.4 Pre-judging checklist

- Talk to the character in English and confirm it neither switches languages nor breaks character.
- Kill the network or fail an asset load and confirm the screen does not go blank.
- Click objects randomly and confirm nothing crashes and the character responds sensibly.

## 10. Prize Tracks

Planned: ElevenLabs (voice), Gemini API, the main placement prizes, and Best Accessibility (UI/UX).

This project does not fit the corporate challenge tracks. Capital One's Nessie challenge is banking, Deloitte × Databricks is a campus agent, and Impiricus is healthcare-professional engagement. None of them connect to what we are building. We are trading corporate tracks for main-track competitiveness. The team should agree on that tradeoff explicitly.

**Open question:** the official opening deck says a team may enter at most 3 sponsor tracks, but does not say whether the MLH tool prizes count against that limit. Someone should ask an organizer.

**Cloudforce HokieAI Side Kick** is a separate entry worth $2,000 and is the only cash prize at the event. It explicitly does not need to connect to our main project. Budget roughly two hours for it as a standalone piece.

## 11. Open Decisions

**Demo language.** Recommendation: pick a language the judges do not speak — Spanish, for example. The whole point of the demo is having the judge personally experience inferring a word. If we demo in English, native English-speaking judges cannot have that experience. Supporting many languages in the product and locking one for the demo are not in conflict.

**Main scene.** Recommendation: the bar.

**Scene 2.** Must share objects with Scene 1.

**Team size and task assignment.**

**Whether MLH tool prizes count toward the 3-sponsor-track limit.**

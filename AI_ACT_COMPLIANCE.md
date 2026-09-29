# EU AI Act / AI Transparency Compliance

**Project:** Genesis Colonies  
**Baseline date:** 2026-09-29  
**Primary classification:** `background_ai`

> Operational compliance record. This is an engineering/compliance baseline, not a substitute for individual legal advice.

## Current assessment

Genesis Colonies is a browser strategy game, not an AI chatbot. Runtime audit found an optional OpenAI moderation supplement for player-name policy and optional speech tooling referenced in legal/privacy documentation. These are background/support functions rather than a direct two-way AI conversation. AI-assisted development and asset workflows may be used; shipped content remains subject to human review.

## Article 50 decision matrix

| Scenario | Current project status | Required action |
| --- | --- | --- |
| Direct two-way interaction with an AI system | See assessment above | If present, inform natural persons clearly from the start of the first interaction unless the AI nature is obvious. |
| Provider of a system generating synthetic text/audio/image/video | Reassess on every release that adds or changes generative output | Evaluate machine-readable marking/detectability under Article 50(2), including technical feasibility and applicable exceptions. |
| Emotion recognition / biometric categorisation | Not identified unless explicitly documented otherwise | If introduced, perform a separate legal/DPIA review and provide required information to exposed persons. |
| Deepfake deployment | Not identified unless explicitly documented otherwise | If content meets the legal deepfake definition, disclose clearly no later than first exposure; artistic/fictional contexts have a context-sensitive disclosure rule. |
| AI-generated public-interest text without human review/editorial control | Not part of the current baseline unless explicitly documented otherwise | Clearly label when Article 50(4) criteria are met. Human editorial review/responsibility must be real and documented if relying on that distinction. |
| AI used only during coding/testing/internal workflow | Present or possible | No blanket visitor-facing “AI generated” label solely because development used AI. Record material use internally and keep human review/accountability. |

## Release gate

Before every production/public release, answer:

- [ ] Does this release add a chatbot, agent, avatar or other direct AI conversation?
- [ ] Does it generate text, audio, images or video for users?
- [ ] Are generated outputs marked/detectable where Article 50(2) applies to us as provider?
- [ ] Does any media resemble a real/existing person, object, place, entity or event in a way that could falsely appear authentic?
- [ ] Is any AI-generated text published to inform the public on a matter of public interest without human editorial review?
- [ ] Does the release use emotion recognition or biometric categorisation?
- [ ] Have privacy notices been updated if personal data is sent to an external AI provider?
- [ ] Is the user-facing disclosure available in the relevant language and accessible before/at first exposure where required?
- [ ] Is human review/editorial responsibility documented for public content where applicable?

## Evidence / provenance

For AI-assisted assets or published synthetic media, record at minimum:

- asset/output identifier and shipped path;
- AI system/provider/model if known;
- whether third-party source material was supplied;
- human author/editor responsible for selection and release;
- whether content depicts or imitates a real person/event/entity;
- whether a visible disclosure is required;
- whether machine-readable provenance/marking is present or technically unavailable.

## Legal references

- Regulation (EU) 2024/1689, Article 50.
- European Commission Guidelines on transparency obligations for certain AI systems, published 20 July 2026.
- Article 50 applies from 2 August 2026, subject to the specific limited transition described by the Commission for certain provider marking duties.

## Change rule

Any PR/feature that introduces **AI chat/agents, generative runtime output, synthetic voice/image/video, emotion recognition, biometric categorisation or automated public-interest publishing** must update this file and the corresponding user-facing legal/transparency notice before release.

---
source: google_drive
drive_file_id: 1ybqf2HLUgEXTQA9-WYSlteQrD4FW53hoQ7fweksYaO4
drive_folder: 02_Technical_and_Code
title: MAROON SOCIAL (SAFESPACE) — MULTI-SURFACE SOCIAL PLATFORM, DYNAMIC UI ENGINE & MAROON ALIGNMENT FIREWALL MASTER SPECIFICATION
mime_type: application/vnd.google-apps.document
created: 2026-08-02T21:19:10.503Z
modified: 2026-08-02T21:19:47.603Z
extracted_via: drive_export_markdown
classification: technical_spec
---

# MAROON SOCIAL (SAFESPACE) — MULTI-SURFACE SOCIAL PLATFORM, DYNAMIC UI ENGINE & MAROON ALIGNMENT FIREWALL MASTER SPECIFICATION

**Canonical Product Name:** Maroon Social (formerly SafeSpace)
**Core Underlying Engine:** Maroon Alignment Engine (Lime Engine / Compatibility Gate / Atlassian Mask)
**Author & Sovereign Lead:** Emmanuel Washington, Founder & CEO
**System Architecture Target:** Enterprise Multi-Surface PWA & Mobile React Native App

## 1. Canonical Product Identity & Vision

### 1.1 Product Evolution

Maroon Social (formerly known as SafeSpace) is the central social engagement, survey distribution, and community governance layer of the Maroon Ecosystem. It transforms traditional social media from an ad-driven, outrage-optimizing extraction network into an identity-verified, alignment-filtered "Safe Space" for community commerce, dialogue, and mutual aid.

### 1.2 Core Architectural Relationship

Maroon Social is not an isolated front-end app. It operates as the primary user interface layer sitting directly on top of the **Maroon Alignment Engine (Lime Engine)** and the **Atlassian Infrastructure Mask**:

- **Atlassian Mask (Sovereign Control Plane + AWS OSB)**: Provides zero-trust network routing (Envoy xDS) and dynamic cloud database sharding.
- **Maroon Alignment Engine**: Intercepts every feed payload, search request, direct message, and profile query to enforce cryptographic belief alignment before data ever reaches the client device.
- **Maroon Social UI Shell**: Renders the allowed content across multiple customizable social skins.

## 2. Dynamic Multi-Surface UI Engine & Profile Customization

### 2.1 The Multi-Surface Layout Switcher

On login or via profile settings (`user_preferences/{uid}.activeSkin`), users toggle their active layout skin without fragmenting their underlying identity, friends, or Market Bucks balance:

1. **Facebook Skin** — Classic newsfeed stream, threaded discussions, community group hubs, event tabs, wall posts, long-form articles. *Use case*: community organization, neighborhood housing assemblies (bee-prec), structured discussions.
2. **Instagram Skin** — Visual media grid, story carousels, photo/video highlights, interactive visual commerce tags. *Use case*: vendor product showcases, artisan crafts, visual storytelling.
3. **Twitter / X Skin** — Real-time short-text thread feed, character-constrained updates, quick replies, trending local topics, quote-posts. *Use case*: rapid local alerts, news updates, community chatter.
4. **TikTok / For You Skin** — Fullscreen vertical swipable video feed, Reanimated 3 gesture handlers, background audio overlays, video review cards. *Use case*: Onita's Market food reviews, chef showcases, viral vendor promotions.

### 2.2 Profile Customization & Customizable Tab System

- **MySpace / Facebook Style Customization**: Users decorate profile background, accent colors, bio banners, featured badges.
- **Customizable Tab Bar** (`user_preferences/{uid}.pinnedTabs[]`):
  - Default Tabs: `[ For You ] [ Onitas ] [ Explore ] [ Local ] [ Groups ]`
  - Pinnable Custom Tabs: specific vendor stores, favorite community groups, hyper-local "Near Me" feeds (tight mile radius), saved posts, live streams. Pinned tabs sync across mobile and web.

## 3. The Lime Engine / Maroon Alignment Firewall Architecture

### 3.1 Belief Rings & Alignment Vectors

Every profile is assigned a multi-dimensional Alignment Vector ("Belief Rings") constructed deterministically by `ring_generator.rs`:

- **Data Ingestion**: Verified government IDs (MIVL Tier 2), voter registration records, connected social history, explicit belief questionnaires.
- **Ring Assignment**: If an entity lacks verified primary data for a specific vector, they do not receive the ring.

### 3.2 Symmetrical Bidirectional Compatibility Rules

Interaction rules are enforced symmetrically in two directions. If User A sets a rule excluding Belief X:

- User A cannot see content, comments, or profiles belonging to entities holding Belief X.
- Entities holding Belief X cannot see User A's content, comments, or profile.

### 3.3 Absolute Existence Denial

Enforced at the server boundary via `compatibility_gate.rs` (gRPC interceptor):

- **Zero Payload Delivery**: Unaligned entities are scrubbed from database queries prior to response serialization.
- **Complete Invisibility**: Unaligned users do not appear in search results, friend recommendations, group member lists, or direct URL lookups. To the unaligned party, the user literally does not exist on the platform.

### 3.4 The Reciprocity Principle

Users cannot demand verification or alignment proofs from others that they have not provided themselves:

- To require ID-verified interactions, the user must be ID-verified.
- To filter by specific political or social rings, the user must hold those verified rings.

### 3.5 Unverified Actor Isolation (`unverified_isolation.rs`)

Unverified or unranked users (MIVL Tier 0) are sandboxed into isolated data pools. They cannot view or interact with protected safe space communities until they pass identity verification.

## 4. Maroon Council AI Entity Instances

### 4.1 Dedicated AI Instance per Entity (`maroon_council_config/{entityId}`)

Every individual profile, registered business, and community group gets a dedicated "Maroon Council" AI instance:

- **Configuration**: Powered by fine-tuned models with rolling 30-day activity context.
- **Tones**: Selectable personality tones (professional, casual, community).

### 4.2 "Talk to Your Council" Chat Interface

Every user profile features a private "Talk to your Council" chat interface providing:

- Personal activity analytics and reputation score breakdowns.
- Market Bucks wallet balance tracking and redemption advice.
- Business insights for merchants (sales trends, inventory alerts, EBT eligibility checks, conversion recommendations).
- Automated community moderation assistance for group managers.

## 5. Unified Trust Ledger, Market Bucks & Comms Protocols

### 5.1 Trust Ledger & Verified Shadow Identity

- **Verified Shadow Identity**: Users maintain a pseudonymous public handle outward, linked securely to verified real-world KYC/biometric data inward.
- **Trust Ledger**: Append-only audit log recording every verified action (transactions, reviews, surveys, identity checks) to generate a dynamic, reputation-scored Trust Score.

### 5.2 Market Bucks Loyalty Wallet

- **Fungible Reward Credits**: Unified points engine issuing Market Bucks for completing checkout surveys, writing verified reviews, or participating in cross-vendor promotions.
- **Cross-Domain Redemption**: Market Bucks earned via healthcare or social surveys can be spent on groceries in Onita's Market or redeemed for service vouchers.

### 5.3 Integrated Comms Layer (Fluxer / WebRTC)

- Built-in direct messaging, group chat, and WebRTC voice/video calls (`/components/comms`).
- All communications are encrypted, identity-bound, and monitored by Council safety alerts for policy breaches.

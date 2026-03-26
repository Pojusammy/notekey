# Music Note & Tonic Solfa Tool PRD

## 1. Product Introduction

### Product Name
Working title: **NoteKey**

### Product Summary
NoteKey is a web-based music utility built for singers, instrumentalists, choir members, music directors, and church musicians. The product helps users do two things quickly:

1. **Detect a sung or played note instantly** and map it to tonic solfa relative to a chosen key.
2. **Upload an audio or video recording** and extract the main melodic line into note names and tonic solfa for practice, transcription, rehearsal, and performance preparation.

The product is designed to simplify musical analysis for users who may not want to work through complex DAWs, notation software, or advanced theory tools. The experience should feel clean, immediate, and musician-friendly rather than technical or intimidating.

### Problem Statement
Musicians often need to identify notes, confirm pitch, and break down short melodic phrases from recordings. Existing music software is often too complex, too expensive, or not optimized for quick everyday use. Many users just want to:

- sing or play a note and know what it is instantly
- identify the tonic solfa of a phrase from a recording
- quickly analyze an interlude or melodic passage without manual transcription
- choose the song key manually when they already know it

There is a gap for a lightweight product that provides these capabilities in a fast and accessible format.

### Core Value Proposition
NoteKey helps musicians move from **hearing** to **understanding** faster by turning pitch and melody into readable note and solfa output in seconds.

### Product Goals
- Provide instant and accurate single-note detection from microphone input.
- Allow users to upload recordings and extract the primary melodic phrase.
- Convert detected notes into tonic solfa based on a selected or detected key.
- Keep the user interface simple, fast, and accessible.
- Build a technical foundation that can support future features such as chord detection, rhythm analysis, and export tools.

### Non-Goals for V1
The first version will **not** aim to:
- perfectly transcribe full dense multi-instrument arrangements
- generate complete sheet music for full songs
- provide advanced DAW-level editing workflows
- offer perfect syncopation or harmonic analysis across all genres
- support collaborative editing or notation authoring

### Target Users
- Choir members and music ministers
- Vocalists practicing scales, songs, and harmonies
- Instrumentalists learning interludes and riffs
- Church musicians transcribing praise and worship phrases
- Music students training ear recognition and tonic solfa reading
- Music teachers who need quick melodic breakdown tools

### Primary Use Cases
1. A singer hums a note and instantly sees the note name and solfa.
2. A user uploads a church ministration clip to identify the melodic interlude.
3. A keyboardist selects the song key and converts a phrase into tonic solfa.
4. A student uses the app to train pitch recognition and melody reading.

---

## 2. Product Scope

### Core Modules
#### A. Note Detector
Live microphone-based pitch detection for a single sung or played note.

**Outputs:**
- note name
- frequency in Hz
- pitch offset in cents
- tonic solfa relative to selected key
- optional indication if the note is likely tonic

#### B. Recording Analyzer
Upload-based melody extraction from audio or video recordings.

**Outputs:**
- detected melodic notes
- tonic solfa representation
- optional phrase segmentation
- timestamps for note groupings
- confidence score or quality indicator where possible

#### C. Key Selection Layer
A persistent control that lets the user:
- choose the musical key manually
- reuse a previous key
- optionally trigger automatic key suggestion in later versions

#### D. History / Saved Sessions
A lightweight history section where users can revisit prior note detections and uploaded analyses.

---

## 3. Functional Requirements

### 3.1 Note Detector
- User can allow microphone access in browser.
- User can start and stop live detection.
- System should process audio in near real time.
- System should detect the fundamental pitch of a sustained sung or played note.
- System should display the nearest note name.
- System should display tuning deviation in cents.
- System should display the note’s tonic solfa relative to the currently selected key.
- System should support sharps and flats where relevant.
- System should handle silence or noisy input gracefully.

### 3.2 Recording Analyzer
- User can upload audio files.
- User can upload video files from which audio is extracted automatically.
- User can optionally trim a recording before analysis.
- User can specify the song key before running analysis.
- System should extract the most prominent melodic line from the recording.
- System should convert detected note sequences into tonic solfa.
- System should show grouped phrase output in readable sections.
- System should allow the user to replay the source clip while viewing output.
- System should show a processing state and final result state.

### 3.3 History
- User can view past analyses.
- User can reopen a previous result.
- User can delete saved sessions.
- User can optionally rename saved analyses.

### 3.4 Error Handling
- System should notify the user when audio quality is too poor.
- System should notify the user when melody extraction confidence is low.
- System should handle unsupported file formats.
- System should handle upload size limits and timeouts.

---

## 4. Technical Specifications

### 4.1 Platform Strategy
**V1 Platform:** Responsive web application

A web-first product reduces development overhead, enables rapid validation, and supports both desktop and mobile browser usage. It is the fastest path to testing microphone capture, file uploads, and analysis workflows.

### 4.2 Recommended Tech Stack

#### Frontend
- **Framework:** Next.js
- **Language:** TypeScript
- **Styling:** Tailwind CSS
- **UI Components:** ShadCN UI
- **State Management:** React Context for simple state, with Zustand if state grows
- **Forms / Validation:** React Hook Form + Zod
- **Audio Visualization:** custom canvas/SVG waveform or lightweight waveform library

#### Backend
- **API Framework:** FastAPI
- **Language:** Python
- **Background Jobs:** Celery or RQ for asynchronous audio processing
- **Task Broker:** Redis
- **Authentication:** NextAuth/Auth.js or Clerk depending on product scope

#### Audio / Media Processing
- **Media Handling:** FFmpeg for format normalization and audio extraction from video
- **Pitch Detection:** librosa-based pitch detection or similar F0 estimation approach for live note analysis
- **Melody Transcription:** Basic Pitch or equivalent for converting audio to note events
- **Optional Stem Separation (future/advanced):** Demucs or similar source separation tool

#### Data & Storage
- **Database:** PostgreSQL
- **ORM / Query Layer:** Prisma for app-side relational access, or SQLAlchemy if backend handles models centrally
- **Object Storage:** AWS S3, Cloudflare R2, or Supabase Storage for uploaded media and processed assets
- **Caching / Session Data:** Redis

#### Infrastructure / DevOps
- **Frontend Hosting:** Vercel
- **Backend Hosting:** Railway, Render, Fly.io, or AWS depending on scale
- **Containerization:** Docker
- **Observability:** Sentry for error monitoring, PostHog for product analytics
- **CI/CD:** GitHub Actions

### 4.3 Supported File Types
**Audio:** MP3, WAV, M4A, AAC

**Video:** MP4, MOV, WebM

### 4.4 Performance Targets
- Live note detection response target: under 500ms perceived response after stable pitch input
- Short upload analysis target: under 20 seconds for common clips under 60 seconds
- Upload limit for V1: 100MB max file size
- Recommended clip duration for best results: 5 to 60 seconds

### 4.5 Security & Privacy
- Uploaded files should be stored securely and processed in isolated jobs.
- Files should be auto-expired after a configurable retention period unless explicitly saved.
- Audio recordings should not be made public by default.
- Microphone permissions should only be requested when entering the note detection flow.
- User session data and saved analyses should be authenticated where persistence is enabled.

### 4.6 Analytics Requirements
Track:
- note detection starts and completions
- upload analysis starts and completions
- average processing time
- failure reasons
- retention on saved analyses
- most used selected keys
- output export or copy actions (future)

---

## 5. App Architecture

### 5.1 High-Level Architecture
The application should be split into four primary layers:

1. **Client Application Layer**
   - user interface
   - microphone access
   - upload flow
   - results display
   - history view

2. **API Layer**
   - receives requests from frontend
   - validates inputs
   - handles authentication
   - creates analysis jobs
   - returns results and job status

3. **Processing Layer**
   - performs audio extraction
   - normalizes media
   - runs pitch detection or melody transcription
   - maps note events to tonic solfa
   - stores final analysis output

4. **Storage Layer**
   - persists user profiles
   - saves job status and results
   - stores uploaded media and derived artifacts

### 5.2 Architectural Flow
#### A. Note Detector Flow
1. User opens Note Detector.
2. Browser requests microphone permission.
3. Microphone stream is captured client-side.
4. Audio frames are passed to detection logic.
5. Pitch estimation is calculated continuously.
6. Frontend displays stable note, frequency, cents, and tonic solfa.
7. Optional session result is saved.

#### B. Recording Analyzer Flow
1. User uploads audio or video.
2. Frontend sends file metadata and upload request.
3. File is stored in object storage.
4. Backend creates processing job.
5. Processing worker pulls job.
6. FFmpeg extracts and normalizes audio.
7. Melody extraction/transcription engine processes the clip.
8. Key mapping service converts note events into tonic solfa.
9. Results are stored in database.
10. Frontend polls or subscribes to job completion.
11. User views note and solfa output.

### 5.3 Suggested Service Breakdown
#### Frontend Services
- route management
- upload state management
- live mic capture controller
- result renderer
- key selector state

#### Backend Services
- auth service
- upload service
- analysis orchestration service
- note-to-solfa mapping service
- history service

#### Worker Services
- media normalization service
- live/audio pitch processing service
- transcription service
- phrase segmentation service
- cleanup service

### 5.4 Data Model Overview
#### Users
- id
- name
- email
- auth provider
- created_at

#### Analysis Jobs
- id
- user_id
- job_type (note_detection / recording_analysis)
- input_file_url
- selected_key
- status
- created_at
- completed_at
- error_message

#### Analysis Results
- id
- job_id
- note_name
- frequency_hz
- cents_offset
- tonic_solfa
- raw_note_sequence
- solfa_sequence
- timestamps_json
- confidence_score

#### Saved Sessions
- id
- user_id
- title
- result_id
- created_at

### 5.5 API Endpoints (Conceptual)
- `POST /api/note/detect-session`
- `POST /api/upload`
- `POST /api/analyze`
- `GET /api/jobs/:id`
- `GET /api/results/:id`
- `GET /api/history`
- `DELETE /api/history/:id`

### 5.6 Scalability Considerations
- Keep processing asynchronous to avoid blocking frontend response times.
- Separate web/API nodes from worker nodes.
- Store uploads in object storage rather than local disk.
- Use queue-based processing so long-running jobs can scale independently.
- Cache common key mappings and derived analysis metadata where needed.

---

## 6. Design Style

### 6.1 Design Principles
The product should feel:
- **clean**
- **focused**
- **minimal**
- **musician-friendly**
- **fast and calm**

This should not look like engineering software or audio production software. It should feel approachable to someone who only wants quick answers.

### 6.2 Visual Direction
- Large, readable typography
- Generous whitespace
- Clear visual hierarchy
- Simple iconography
- Minimal decorative noise
- Strong emphasis on output readability
- Subtle motion only where it improves feedback

The product should visually balance musical warmth with technical clarity.

### 6.3 Layout Direction
- Centered primary interactions
- Clear two-state flows: idle → active/result
- Single dominant action per screen
- Sticky or consistently visible key selector
- Compact history cards with readable metadata

### 6.4 Tone of UI
The interface should speak in plain language.

Examples:
- “Sing or play a note”
- “Choose key”
- “Upload a clip”
- “Analyzing melody...”
- “Here’s the detected solfa”

Avoid overly technical labels unless they are secondary details.

---

## 7. Design System

### 7.1 System Foundations
The design system should be lightweight but scalable.

#### Core Foundations
- color system
- typography scale
- spacing system
- radius and elevation tokens
- iconography rules
- motion guidelines
- interactive states

### 7.2 Color System
Use semantic naming rather than raw color naming.

#### Suggested Token Structure
- `bg-canvas`
- `bg-surface`
- `bg-surface-elevated`
- `text-primary`
- `text-secondary`
- `text-muted`
- `border-subtle`
- `border-strong`
- `accent-primary`
- `accent-secondary`
- `success`
- `warning`
- `danger`

#### Visual Recommendation
Base UI should use neutral backgrounds with one strong accent color. Since the product is music-related, a calm premium accent such as deep blue, rich green, or muted violet can work well.

Example direction:
- warm off-white or dark neutral background
- clean white or near-black cards
- strong accent for active state and waveform highlights
- soft border tones and muted secondary text

### 7.3 Typography
Typography should feel modern, premium, and highly readable.

#### Recommendations
- **Primary font:** Inter, Geist, or SF Pro style equivalent
- **Display usage:** medium to semibold for large pitch/note outputs
- **Body usage:** regular to medium for general UI

#### Typography Roles
- Display XL: live note output
- Heading L: page titles
- Heading M: section titles
- Body M: standard content
- Body S: metadata and support copy
- Mono S/M: optional note sequences, timestamps, technical readouts

### 7.4 Spacing System
Adopt a consistent spacing scale such as:
- 4
- 8
- 12
- 16
- 24
- 32
- 48
- 64

Use whitespace generously, especially around primary input and result blocks.

### 7.5 Radius & Elevation
- Inputs and cards: medium radius
- Modal surfaces: larger radius
- Shadows: subtle and soft
- Use depth sparingly to keep interface calm

### 7.6 Core Components
#### Inputs
- file upload dropzone
- key selector dropdown
- text inputs for saved titles
- search field for history (future)

#### Actions
- primary button
- secondary button
- icon button
- mic action button

#### Feedback
- loading spinner
- progress bar
- toast notifications
- inline status messages
- empty states
- low-confidence warning state

#### Data Display
- result card
- phrase sequence block
- waveform/timeline display
- saved session card
- note badge / solfa badge

### 7.7 Interaction States
Every core component should support:
- default
- hover
- focus
- active
- disabled
- loading
- error
- success

### 7.8 Accessibility Requirements
- meet WCAG contrast standards
- support keyboard navigation
- visible focus states
- meaningful labels for icons and microphone controls
- accessible upload interactions
- avoid color-only status communication
- responsive design across mobile and desktop browsers

### 7.9 Motion Guidelines
Use motion to reinforce system response, not decoration.

Good motion use cases:
- live pitch detection stabilization
- upload progress feedback
- subtle result reveal transitions
- waveform pulse on active listening

Avoid excessive animation that distracts from reading or listening tasks.

---

## 8. Suggested MVP Release Scope

### Include in MVP
- responsive web app
- note detector
- manual key selection
- upload audio/video
- melody/interlude extraction for short clips
- tonic solfa output
- saved result history
- secure processing and storage

### Exclude from MVP
- native mobile apps
- advanced rhythm/syncopation visualization
- chord detection
- full arrangement transcription
- sheet music generation
- collaborative workspaces
- DAW plugins

---

## 9. Future Expansion
- automatic key estimation
- better phrase segmentation
- stem-separated melody mode
- export to MIDI or PDF
- chord suggestions
- rhythm breakdown and syncopation visualization
- ear training modules
- mobile apps
- offline practice mode

---

## 10. Success Metrics
- percentage of successful live note detections
- upload-to-result completion rate
- median analysis time
- repeat usage per user
- saved session rate
- user satisfaction on result usefulness
- reduction in failed or low-confidence analyses over time

---

## 11. Product Summary
NoteKey should launch as a focused and reliable tool for quick note recognition and melody-to-solfa conversion. The experience must stay simple enough for everyday musicians while the underlying architecture remains strong enough to support future music intelligence features. The goal is not to replace full music production software, but to become the fastest and easiest way for musicians to identify notes, understand melodic phrases, and practice with confidence.


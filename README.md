          ┌───────────────┐
          │  Video Upload │
          └──────┬────────┘
                 ↓
        ┌──────────────────┐
        │ Video Preprocessor│
        │ (FFmpeg / OpenCV)│
        └──────┬───────────┘
               ↓
 ┌────────────────────────────────┐
 │  Feature Extraction Pipelines  │
 │                                │
 │ 🎵 Audio Analyzer               │
 │ 🏃 Motion Analyzer              │
 │ ⏱️ Rally Detector               │
 │ 🧱 Scene Boundary Detector      │
 └──────────────┬─────────────────┘
                ↓
      ┌─────────────────────┐
      │  Event Scoring Engine│
      │ (Weighted heuristics)│
      └─────────┬───────────┘
                ↓
     ┌─────────────────────────┐
     │  LLM Reasoning Layer    │
     │ ("Why is this exciting")│
     └─────────┬──────────────┘
               ↓
   ┌────────────────────────────┐
   │ Highlight Clip Generator   │
   │ (timestamps → video cuts)  │
   └─────────┬──────────────────┘
             ↓
   ┌────────────────────────────┐
   │ Frontend / Results Viewer  │
   │ (clips + explanations)     │
   └────────────────────────────┘

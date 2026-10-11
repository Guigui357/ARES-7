# ARES-7 Mobile (Android + iOS)

Cross-platform mobile client foundation for the ARES-7 project. This is an additive mobile app; it does not replace or rewrite the existing Python/Linux application.

## Goals

- Run language-model inference on-device, with no ARES-7 server and no paid API.
- Work on Android and iOS from one Flutter UI.
- Offer offline speech recognition and offline speech synthesis.
- Let users import/download a compatible model and keep chats on-device.

## Current status

**UI prototype only — not yet an offline AI release.** The Flutter shell currently provides the ARES-7 chat layout and clearly labels the model as not configured. It does not pretend to generate AI answers or record/process speech yet. Native inference and speech engines must be integrated and tested before distributing an APK/IPA.

## Build the UI prototype

Install Flutter stable and the Android SDK (Android), or Xcode on macOS (iOS), then:

```sh
cd mobile
flutter pub get
flutter run
```

Build Android APK:

```sh
flutter build apk --release
```

Build iOS (requires macOS + Xcode):

```sh
flutter build ios --release
```

## Proposed runtime architecture

- **LLM:** llama.cpp compiled as a native library for Android (arm64-v8a) and iOS (arm64), using a small quantized GGUF model. Use a bounded context and one inference worker to limit RAM and heat.
- **Speech-to-text:** an offline engine such as whisper.cpp, with a small model downloaded explicitly by the user.
- **Text-to-speech:** an offline voice engine such as Piper, provided compatible mobile native builds and licenses are verified.
- **Storage:** app-private files for models and SQLite for chat history; no server required.
- **Network:** only optional model downloads and updates. Once assets are installed, chat and speech processing should work in airplane mode.

Do not bundle large model files in the app package by default. Show model size, free-space needs, license, and minimum recommended RAM before downloading. Use platform-native model storage and allow deletion.

## Acceptance tests before calling it functional

1. Launch and chat with a downloaded GGUF model in airplane mode.
2. Confirm no remote inference requests occur.
3. Record speech, transcribe offline, generate a response locally, and speak it offline.
4. Test app backgrounding, interruption, low storage, missing model, and model load failures.
5. Test Android and iPhone separately; a successful Android build does not prove iOS works.

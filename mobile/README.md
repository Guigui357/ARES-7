# ARES-7 Mobile (Android + iOS)

Cross-platform Flutter app for the ARES-7 project. This is additive and does not replace the existing Python/Linux application.

## Current implementation

- Flutter chat UI.
- Local GGUF file import into the app's private documents directory.
- llama_cpp_dart 0.9.x integration, using llama.cpp for on-device token generation.
- A bounded 2,048-token context and a maximum of 192 generated tokens per reply.
- No ARES-7 server and no paid inference API.
- Offline speech-to-text and text-to-speech are **not integrated yet**.

The source code has been added to the feature branch, but this environment did not run Flutter dependency resolution or build Android/iOS binaries. Treat this as an integration under development, not a verified store-ready release.

## Requirements

- Flutter / Dart compatible with Dart 3.9 or newer.
- Android: Android SDK and a physical arm64 Android device recommended.
- iOS: macOS + Xcode and an iPhone for device testing.
- A compatible, instruction-tuned GGUF model. Models are not bundled in the app; choose a quantized model that fits the phone's RAM and storage.

## Android

The package supplies the Android CPU native library through Flutter's native-assets hook. From the repository root:

```sh
cd mobile
flutter pub get
flutter analyze
flutter run
```

Build a release APK:

```sh
flutter build apk --release
```

The first version uses CPU inference on Android for broad compatibility. Larger models can be slow or exhaust memory; start with a small Q4-quantized model and close other memory-heavy apps.

## iOS native framework setup

The Dart integration calls LlamaEngine.spawnFromProcess on iOS. iOS must embed the native llama.xcframework before inference can run; adding the Dart dependency alone does not embed that framework.

1. On a Mac, obtain the matching llama_cpp_dart 0.9.x source/release and build its Apple framework using its documented tool/build_apple_xcframework.sh process.
2. In Xcode, open mobile/ios/Runner.xcworkspace.
3. Add llama.xcframework to the Runner target and select **Embed & Sign** where Xcode offers that option.
4. Run `cd mobile && flutter pub get && flutter build ios`, then install on a physical iPhone.
5. Verify model import and generation in airplane mode. The iOS simulator is not a substitute for a physical-device memory/performance test.

The exact framework artifact must match the package's pinned llama.cpp ABI. Do not copy arbitrary libllama binaries from another build.

## Importing a model

Launch the app and tap the folder/model button. Choose a local .gguf file. The app copies it into its private ares_models directory and loads it. The model stays on the device and can be removed by deleting app data (a model-management/delete UI is still to be added).

Prefer a small instruction-tuned Q4 GGUF model. The app currently sets a 2,048-token context and 192-token reply limit to constrain memory use. Actual RAM requirements vary by model and phone.

## Privacy and network behavior

Inference is performed by llama.cpp on-device. This integration does not send prompts to a server or paid API. Importing a model uses the system file picker; no model download feature is included yet. Once a model is on the device, text generation should not require a network connection.

## Remaining work before release

- Complete the iOS XCFramework integration and verify it on a physical iPhone.
- Run flutter pub get, flutter analyze, and Android/iOS release builds in CI.
- Test several supported GGUF architectures/chat templates; models vary in template compatibility.
- Add cancellation, unload/switch model, model deletion, storage checks, and chat persistence.
- Integrate offline speech-to-text (e.g. whisper.cpp) and offline speech synthesis (e.g. a compatible Piper mobile build).
- Verify airplane-mode behavior, thermal throttling, low-memory handling, app lifecycle, and licensing of each model/voice.

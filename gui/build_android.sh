#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORK_DIR="$(mktemp -d)"

echo ">> [Ziokt Android] Packaging standalone Android APK application..."

# 1. Sync assets into Android project
mkdir -p "$SCRIPT_DIR/android/app/src/main/assets"
cp -r "$SCRIPT_DIR/dist"/* "$SCRIPT_DIR/android/app/src/main/assets/"
rm -rf "$SCRIPT_DIR/android/app/src/main/assets/downloads"

# 2. Check if Gradle is present and can build APK directly
if command -v ./gradlew >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/android/gradlew" ]; then
    echo "  -> Attempting Gradle build..."
    (cd "$SCRIPT_DIR/android" && ./gradlew assembleRelease || ./gradlew assembleDebug) || true
    APK_OUT=$(find "$SCRIPT_DIR/android/app/build/outputs/apk" -name "*.apk" 2>/dev/null | head -n 1 || true)
    if [ -n "$APK_OUT" ] && [ -f "$APK_OUT" ]; then
        echo "  ✓ Gradle built: $APK_OUT"
        mkdir -p "$SCRIPT_DIR/downloads"
        cp "$APK_OUT" "$SCRIPT_DIR/downloads/ziokt-mobile-android.apk"
        exit 0
    fi
fi

# 3. Direct AOSP toolchain packaging (aapt + javac + d8 + zipalign + apksigner)
echo "  -> Using direct AOSP toolchain packaging..."
ANDROID_JAR="/tmp/android-30.jar"
if [ ! -f "$ANDROID_JAR" ]; then
    curl -sSL "https://raw.githubusercontent.com/Sable/android-platforms/master/android-30/android.jar" -o "$ANDROID_JAR"
fi

R8_JAR="/tmp/r8.jar"
if [ ! -f "$R8_JAR" ]; then
    curl -sSL "https://maven.google.com/com/android/tools/r8/8.2.42/r8-8.2.42.jar" -o "$R8_JAR"
fi

# Package resources and generate R.java
mkdir -p "$WORK_DIR/gen" "$WORK_DIR/classes" "$WORK_DIR/dex"
aapt package -f -m \
    -M "$SCRIPT_DIR/android/app/src/main/AndroidManifest.xml" \
    -S "$SCRIPT_DIR/android/app/src/main/res" \
    -I "$ANDROID_JAR" \
    -A "$SCRIPT_DIR/android/app/src/main/assets" \
    --min-sdk-version 24 \
    --target-sdk-version 34 \
    --version-code 10000 \
    --version-name 1.0.0 \
    --replace-version \
    -F "$WORK_DIR/unaligned.apk" \
    -J "$WORK_DIR/gen"

# Compile Java sources
javac -cp "$ANDROID_JAR" -d "$WORK_DIR/classes" \
    "$SCRIPT_DIR/android/app/src/main/java/com/ziokt/client/MainActivity.java" \
    "$WORK_DIR/gen/com/ziokt/client/R.java"

# Compile bytecode to Dalvik dex
java -cp "$R8_JAR" com.android.tools.r8.D8 \
    --lib "$ANDROID_JAR" \
    --output "$WORK_DIR/dex" \
    "$WORK_DIR/classes/com/ziokt/client"/*.class

# Add classes.dex into APK
(cd "$WORK_DIR/dex" && aapt add "$WORK_DIR/unaligned.apk" classes.dex)

# 4-byte boundary zipalign
zipalign -f -v -p 4 "$WORK_DIR/unaligned.apk" "$WORK_DIR/aligned.apk" >/dev/null

# Generate keystore if missing
DEBUG_KS="$WORK_DIR/debug.keystore"
keytool -genkeypair -v -keystore "$DEBUG_KS" -storepass android -alias androiddebugkey -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" -noprompt

# Cryptographically sign APK (v1, v2, v3)
mkdir -p "$SCRIPT_DIR/downloads"
apksigner sign --ks "$DEBUG_KS" --ks-pass pass:android --out "$SCRIPT_DIR/downloads/ziokt-mobile-android.apk" "$WORK_DIR/aligned.apk"

# Verify signature
apksigner verify -v "$SCRIPT_DIR/downloads/ziokt-mobile-android.apk"

# Sync to gateway
mkdir -p "$ROOT_DIR/gateway/gui/downloads"
cp "$SCRIPT_DIR/downloads/ziokt-mobile-android.apk" "$ROOT_DIR/gateway/gui/downloads/ziokt-mobile-android.apk"

rm -rf "$WORK_DIR"
echo ">> [Ziokt Android] Build successful! Produced $(ls -lh "$SCRIPT_DIR/downloads/ziokt-mobile-android.apk")"

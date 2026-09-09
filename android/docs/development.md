# Android Development on the Linux Server

## Scope and Verified State

Host tools were installed and checked on 2026-09-09, on Ubuntu 24.04 x86-64.
Wireless ADB pairing, connection, and shell access were verified against the
Samsung Galaxy A33 (SM-A336B), running Android 16 / API 36. Its reported ABIs are
`arm64-v8a`, `armeabi-v7a`, and `armeabi`.

No application has been built, installed, or tested yet. Camera lifecycle,
screen-off operation, lock-screen UI, and hardware-button behavior are separate
device experiments, not consequences of successful ADB setup.

## Installed Tools

| Tool | Verified version |
| --- | --- |
| OpenJDK / javac | 21.0.12, Ubuntu package `21.0.12+8-1~24.04` |
| Android SDK Command-line Tools | 23.0 |
| Android CLI | 1.0.16261425 |
| Android SDK Platform-Tools | 37.0.1-15733141 |
| ADB protocol tool version | 1.0.41 |
| Android SDK Platform | API 36, revision 2 |
| Android SDK Build-Tools | 36.0.0 |
| Android framework sources | API 36, revision 1 |

`unzip` and the system/Java CA certificate packages are also installed. JDK tools
include `keytool`, `jarsigner`, and `jdb`; SDK Build-Tools include `aapt2`, `d8`,
`zipalign`, and `apksigner`.

Android Studio, emulator/system images, NDK, and CMake are not needed for initial
Kotlin/Java development against the physical device and have not been installed.
Do not install Ubuntu's system Gradle as the project build tool. Choose compatible
AGP, Kotlin, and Gradle versions with the first application implementation and
commit its Gradle Wrapper and configuration inside this component. Libraries
such as CameraX, Compose, and Vosk are project dependencies, not global packages.

## Location and Environment

The SDK is user-owned and outside the repository:

```text
$HOME/.local/share/android-sdk/
    cmdline-tools/23.0/
    platform-tools/
    platforms/android-36/
    build-tools/36.0.0/
    sources/android-36/
```

On this Ubuntu x86-64 host, the selected JDK is
`/usr/lib/jvm/java-21-openjdk-amd64`.

The machine-local helper `$HOME/.config/memotrace/android-env.sh` sets `JAVA_HOME`,
`ANDROID_HOME`, and the relevant `PATH` entries. It is sourced by `.profile` and
interactive `.bashrc`. For a shell that was already open before installation:

```bash
. "$HOME/.config/memotrace/android-env.sh"
```

Other machines may use different SDK/JDK locations. Application build scripts
must use standard environment variables or an ignored `local.properties`, not
source this host-specific helper or hardcode a developer's home directory.
`ANDROID_SDK_ROOT` is not set; use `ANDROID_HOME`.

## Installation Provenance

System dependencies came from the configured Ubuntu repositories:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends openjdk-21-jdk-headless unzip ca-certificates
```

The bootstrap archive was obtained from
[Google's official repository](https://dl.google.com/android/repository/commandlinetools-linux-16111833_latest.zip).
Its SHA-1, published in Google's HTTPS
[SDK repository metadata](https://dl.google.com/android/repository/repository2-3.xml),
was verified before extraction:

```text
e025545c62a8e64c7559119566a569fb1dec5f60
```

Extracted command-line tools are located at `cmdline-tools/23.0`, including their
`bin/`, `lib/`, and `source.properties`. Google SDK terms were explicitly accepted
by the user for this installation. A new installation requires its operator to
review and accept the applicable [SDK terms](https://developer.android.com/studio/terms).
Do not commit SDK archives, license-acceptance state, or downloaded binaries.

The SDK packages were installed through Google's tool. In Command-line Tools 23,
`sdkmanager` is a deprecated compatibility entry point; prefer the new CLI:

```bash
android sdk install "platform-tools"
android sdk install "platforms/android-36"
android sdk install "build-tools/36.0.0"
android sdk install "sources/android-36"
android sdk list
```

These commands select stable packages by default. Review changes before updating;
the table above records this setup, not a guarantee about future latest versions.

## Verify the Tools

```bash
java -version
javac -version
android --version
adb version
"$ANDROID_HOME/build-tools/36.0.0/aapt2" version
"$ANDROID_HOME/build-tools/36.0.0/apksigner" version
adb devices -l
```

## Pair Over Wi-Fi

Use Android's TLS-based Wireless debugging, not legacy `adb tcpip 5555`. No USB
cable, root access, OEM unlock, or factory reset is required for this workflow.

1. Connect the phone to the trusted home Wi-Fi network reachable from the server.
   The server may be connected by Ethernet to the same LAN.
2. If Developer options are hidden, open Settings > About phone > Software
   information and tap Build number seven times; authenticate on the phone if asked.
3. Open Developer options > Wireless debugging and enable it for the trusted
   network. Keep the phone unlocked during initial pairing.
4. Choose Pair device with pairing code. Note the pairing IP/port and six-digit
   code, and keep that dialog open while running the pairing command.
5. Run `adb pair <PHONE_IP>:<PAIRING_PORT>` and enter the temporary code at the
   prompt. This is not the phone's unlock PIN; never record it in project files.
6. Return to the main Wireless debugging page and note its connection IP/port.
   This port is different from the pairing port.
7. If automatic connection does not occur, run
   `adb connect <PHONE_IP>:<CONNECTION_PORT>`.

Check the connection using the endpoint shown by `adb devices -l`:

```bash
DEVICE='<PHONE_IP>:<CONNECTION_PORT>'
adb devices -l
adb -s "$DEVICE" shell getprop ro.product.model
adb -s "$DEVICE" shell getprop ro.build.version.release
adb -s "$DEVICE" shell getprop ro.build.version.sdk
```

The device must appear as `device`, not `offline` or `unauthorized`. The verified
reference device reported `SM-A336B`, `16`, and `36`, respectively.

## Reconnection and Safety

Pairing keys persist under `$HOME/.android/`. Do not copy them into the repository
or share them; run ADB as the normal user, not with `sudo`. To revoke this host,
forget it in the phone's Wireless debugging settings. An ordinary
`adb disconnect <PHONE_IP>:<CONNECTION_PORT>` disconnects without revoking pairing.

The phone's IP and connection port can change, especially after a Wi-Fi change,
reboot, or toggling Wireless debugging. Reconnect to the current connection port;
do not reuse an expired pairing port. Pair again only if authorization was lost.

`adb mdns check` and `adb mdns services` help diagnose automatic discovery. During
initial setup, no services were discovered, but explicit IP/port pairing and
connection worked. Do not assume automatic reconnection has been verified.

The host ADB server was verified listening only on `127.0.0.1:5037`. Do not use
`adb -a`, open ADB ports on the Internet, or add broad firewall exceptions. Do not
disable Samsung security controls without diagnosing a specific blocker.

Application upload is a separate authenticated/encrypted protocol. Production
MemoTrace operation must not require Developer options or an ADB connection.
When testing battery use and background behavior, repeat measurements without an
active debugger or ADB session. Logs and screenshots may contain private data;
limit collection to the app under test and never publish unredacted captures.

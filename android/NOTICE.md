# Dependency Provenance

Original recorder code, tests, generated vector artwork and documentation:
`AGPL-3.0-only`. Synthetic fixtures are authored for this project; no captured
personal data or third-party dataset is included. Instrumented tests generate a
small bitmap locally. Real camera testing must use an operator-approved scene.

Direct dependency pins live in component Gradle files; repositories are Google's
official Maven, Maven Central and Gradle Plugin Portal. No vendored sibling source,
unversioned snapshot or model is consumed. Preserve dependency license/notice
metadata when distributing; do not treat external libraries as AGPL-authored code.

| Dependency | Source / license |
| --- | --- |
| Gradle 8.13 Wrapper (generated scripts/JAR) | [Gradle](https://github.com/gradle/gradle/tree/v8.13.0), Apache-2.0; generated script headers retained |
| AGP 8.13.2; AndroidX CameraX 1.5.3, core 1.17.0, lifecycle 2.9.4, test 1.7.0 / ext.junit 1.3.0 / Espresso 3.7.0 | [Android Open Source](https://android.googlesource.com/), Apache-2.0 |
| Kotlin 2.2.21 and stdlib | [JetBrains](https://github.com/JetBrains/kotlin/tree/v2.2.21), Apache-2.0 |
| JUnit 4.13.2 | [JUnit](https://github.com/junit-team/junit4/tree/r4.13.2), EPL-1.0 |
| Robolectric 4.16.1 | [Robolectric](https://github.com/robolectric/robolectric), MIT |
| JaCoCo 0.8.13 | [JaCoCo](https://github.com/jacoco/jacoco/tree/v0.8.13), EPL-2.0 |
| Spotless 7.2.1 | [DiffPlug](https://github.com/diffplug/spotless), Apache-2.0 |
| ktlint 1.7.1 | [ktlint](https://github.com/pinterest/ktlint), MIT |

OpenJDK is a host tool under GPL-2.0 with Classpath Exception, not bundled app code.
Android SDK packages use their separately accepted Google SDK terms. Gradle and
SDK distributions/dependency caches remain outside source control. Full transitive
license/notice and release-artifact review is required before public distribution;
this prototype adds no custom packaging rule that strips dependency notices.
